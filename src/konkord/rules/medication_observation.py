"""Rule pack: medication order preservation checks (HL7v2 ORC/RXE/RXR ->
FHIR MedicationRequest).

Scope: covers scenario-registry.csv SC-031 (dose unit changed), SC-032
(frequency lost), SC-033 (ingredient code changed), SC-034 (route altered),
SC-035 (dosage timing shifted -- treated as a frequency check, since the
simplified RXE-1 field used here does not distinguish timing from
frequency), SC-036 (prescription status altered), SC-037 (medication
quantity changed -- treated as dose amount), SC-038 (refill information
lost, RXE-12 vs MedicationRequest.dispenseRequest.numberOfRepeatsAllowed).
SC-040 (request confused with administration) is out of scope for this
rule pack -- it requires comparing resource types across records (is the
matching target resource a MedicationRequest or a MedicationAdministration?),
not a single order-pair comparison -- and is instead handled in
`reconciliation.engine.compare_many_medications()`.

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from .registry import register, RuleResult

DOMAIN = "medication"

# HL7v2 Table 0038 (Order Status, subset) -> FHIR MedicationRequest.status.
_STATUS_MAP = {"A": "active", "CM": "completed", "CA": "cancelled", "DC": "stopped", "HD": "on-hold"}


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _med_codes(target: dict) -> list:
    coding = target.get("medicationCodeableConcept", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


def _dosage(target: dict) -> dict:
    instructions = target.get("dosageInstruction", [])
    return instructions[0] if instructions else {}


@register("MEDICATION.CODE", domain=DOMAIN)
def check_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source medication code supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no MedicationRequest resource")
    codes = _med_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Medication ingredient code preservation")


@register("MEDICATION.DOSE_AMOUNT", domain=DOMAIN)
def check_dose_amount(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("dose_amount"):
        return RuleResult("INDETERMINATE", explanation="No source dose amount supplied")
    if not target:
        return RuleResult("FAIL", source["dose_amount"], "", "Target has no MedicationRequest resource")
    dose_qty = _dosage(target).get("doseAndRate", [{}])[0].get("doseQuantity", {})
    s_val, t_val = _dec(source["dose_amount"]), _dec(dose_qty.get("value"))
    match = s_val is not None and t_val is not None and s_val == t_val
    return RuleResult("PASS" if match else "FAIL", source["dose_amount"], dose_qty.get("value"), "Dose amount preservation")


@register("MEDICATION.DOSE_UNIT", domain=DOMAIN)
def check_dose_unit(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("dose_unit"):
        return RuleResult("INDETERMINATE", explanation="No source dose unit supplied")
    if not target:
        return RuleResult("FAIL", source["dose_unit"], "", "Target has no MedicationRequest resource")
    dose_qty = _dosage(target).get("doseAndRate", [{}])[0].get("doseQuantity", {})
    t_unit = dose_qty.get("code") or dose_qty.get("unit") or ""
    match = source["dose_unit"] == t_unit
    return RuleResult("PASS" if match else "FAIL", source["dose_unit"], t_unit, "Dose unit preservation (literal comparison only)")


@register("MEDICATION.ROUTE", domain=DOMAIN)
def check_route(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("route"):
        return RuleResult("INDETERMINATE", explanation="No source route (RXR-1) supplied")
    if not target:
        return RuleResult("FAIL", source["route"], "", "Target has no MedicationRequest resource")
    coding = _dosage(target).get("route", {}).get("coding", [])
    routes = [c.get("code", "") for c in coding]
    match = source["route"] in routes
    return RuleResult("PASS" if match else "FAIL", source["route"], routes, "Route of administration preservation")


def _repeat_frequency_string(target: dict) -> str:
    """Render FHIR dosageInstruction.timing.repeat as the same
    "<frequency>/<period><periodUnit>" shorthand this prototype uses on the
    HL7v2 RXE-1 side, for FHIR resources (such as real Synthea exports)
    that encode structured timing.repeat instead of a free-text
    timing.code.text.
    """
    repeat = _dosage(target).get("timing", {}).get("repeat", {})
    frequency, period = repeat.get("frequency"), repeat.get("period")
    if not frequency or not period:
        return ""
    return f"{frequency}/{period}{repeat.get('periodUnit', '')}"


@register("MEDICATION.FREQUENCY", domain=DOMAIN)
def check_frequency(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("frequency"):
        return RuleResult("INDETERMINATE", explanation="No source frequency (RXE-1) supplied")
    if not target:
        return RuleResult("FAIL", source["frequency"], "", "Target has no MedicationRequest resource")
    code_text = _dosage(target).get("timing", {}).get("code", {}).get("text", "")
    repeat_str = _repeat_frequency_string(target)
    target_value = code_text or repeat_str
    match = bool(target_value) and source["frequency"] == target_value
    return RuleResult("PASS" if match else "FAIL", source["frequency"], target_value,
                       "Dosage frequency/timing preservation (literal comparison on timing.code.text, "
                       "falling back to a derived \"<frequency>/<period><periodUnit>\" string from "
                       "timing.repeat when timing.code.text is absent)")


@register("MEDICATION.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="No source order status (ORC-5) supplied")
    expected = _STATUS_MAP.get(source["status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source order status '{source['status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no MedicationRequest resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Prescription status preservation")


@register("MEDICATION.REFILLS", domain=DOMAIN)
def check_refills(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("refills"):
        return RuleResult("INDETERMINATE", explanation="No source number of refills (RXE-12) supplied")
    if not target:
        return RuleResult("FAIL", source["refills"], "", "Target has no MedicationRequest resource")
    s_val = _dec(source["refills"])
    t_val = _dec(target.get("dispenseRequest", {}).get("numberOfRepeatsAllowed"))
    if s_val is None:
        return RuleResult("INDETERMINATE", explanation=f"Source number of refills '{source['refills']}' is not numeric")
    match = t_val is not None and s_val == t_val
    return RuleResult("PASS" if match else "FAIL", source["refills"],
                       target.get("dispenseRequest", {}).get("numberOfRepeatsAllowed"),
                       "Refill count preservation (RXE-12 vs dispenseRequest.numberOfRepeatsAllowed)")


@register("MEDICATION.DATE", domain=DOMAIN)
def check_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("date"):
        return RuleResult("INDETERMINATE", explanation="No source order date/time (ORC-9) supplied")
    raw = source["date"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no MedicationRequest resource")
    authored_on = target.get("authoredOn", "")
    match = bool(authored_on) and authored_on.replace("-", "").replace(":", "").startswith(raw[:8])
    return RuleResult("PASS" if match else "FAIL", raw, authored_on, "Order date preservation (date-level comparison)")
