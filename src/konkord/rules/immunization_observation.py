"""Rule pack: immunization record preservation checks (HL7v2.5.1 VXU^V04
RXA segment -> FHIR R4B Immunization, per the CDC/HL7 Immunization
Implementation Guide and US Core Immunization profile).

Scope: covers scenario-registry.csv SC-151 (vaccine code altered), SC-152
(lot number lost), SC-153 (administration date changed), SC-154
(completion status altered -- e.g. a not-done dose silently recorded as
completed), SC-155 (dose amount/unit changed), SC-156 (manufacturer
dropped), SC-157 (expiration date changed). SC-158 (immunization record
dropped entirely) is out of scope for this rule pack -- it requires
matching across the full set of administered doses in a message/bundle,
not a single administration-pair comparison -- and is instead handled in
`reconciliation.engine.compare_many_immunizations()`.

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from .registry import register, RuleResult

DOMAIN = "immunization"

# HL7v2 Table 0322 (Completion Status, subset) -> FHIR Immunization.status.
_STATUS_MAP = {"CP": "completed", "PA": "completed", "RE": "entered-in-error", "NA": "not-done"}


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _vaccine_codes(target: dict) -> list:
    coding = target.get("vaccineCode", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


@register("IMMUNIZATION.VACCINE_CODE", domain=DOMAIN)
def check_vaccine_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source vaccine code (RXA-5) supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no Immunization resource")
    codes = _vaccine_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Vaccine (CVX) code preservation")


@register("IMMUNIZATION.LOT_NUMBER", domain=DOMAIN)
def check_lot_number(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("lot_number"):
        return RuleResult("INDETERMINATE", explanation="No source lot number (RXA-15) supplied")
    if not target:
        return RuleResult("FAIL", source["lot_number"], "", "Target has no Immunization resource")
    t_lot = target.get("lotNumber", "")
    match = source["lot_number"] == t_lot
    return RuleResult("PASS" if match else "FAIL", source["lot_number"], t_lot, "Lot number preservation")


@register("IMMUNIZATION.DATE", domain=DOMAIN)
def check_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("date"):
        return RuleResult("INDETERMINATE", explanation="No source administration date/time (RXA-3) supplied")
    raw = source["date"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no Immunization resource")
    occurrence = target.get("occurrenceDateTime", "") or target.get("occurrenceString", "")
    match = bool(occurrence) and occurrence.replace("-", "").replace(":", "").startswith(raw[:8])
    return RuleResult("PASS" if match else "FAIL", raw, occurrence, "Administration date preservation (date-level comparison)")


@register("IMMUNIZATION.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("completion_status"):
        return RuleResult("INDETERMINATE", explanation="No source completion status (RXA-20) supplied")
    expected = _STATUS_MAP.get(source["completion_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source completion status '{source['completion_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Immunization resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Completion status preservation")


@register("IMMUNIZATION.DOSE_AMOUNT", domain=DOMAIN)
def check_dose_amount(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("dose_amount"):
        return RuleResult("INDETERMINATE", explanation="No source administered amount (RXA-6) supplied")
    if not target:
        return RuleResult("FAIL", source["dose_amount"], "", "Target has no Immunization resource")
    dose_qty = target.get("doseQuantity", {})
    s_val, t_val = _dec(source["dose_amount"]), _dec(dose_qty.get("value"))
    match = s_val is not None and t_val is not None and s_val == t_val
    return RuleResult("PASS" if match else "FAIL", source["dose_amount"], dose_qty.get("value"), "Administered dose amount preservation")


@register("IMMUNIZATION.DOSE_UNIT", domain=DOMAIN)
def check_dose_unit(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("dose_unit"):
        return RuleResult("INDETERMINATE", explanation="No source administered unit (RXA-7) supplied")
    if not target:
        return RuleResult("FAIL", source["dose_unit"], "", "Target has no Immunization resource")
    dose_qty = target.get("doseQuantity", {})
    t_unit = dose_qty.get("code") or dose_qty.get("unit") or ""
    match = source["dose_unit"] == t_unit
    return RuleResult("PASS" if match else "FAIL", source["dose_unit"], t_unit, "Administered dose unit preservation (literal comparison only)")


@register("IMMUNIZATION.MANUFACTURER", domain=DOMAIN)
def check_manufacturer(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("manufacturer"):
        return RuleResult("INDETERMINATE", explanation="No source manufacturer (RXA-17) supplied")
    if not target:
        return RuleResult("FAIL", source["manufacturer"], "", "Target has no Immunization resource")
    t_manufacturer = target.get("manufacturer", {}).get("display", "")
    match = source["manufacturer"] == t_manufacturer
    return RuleResult("PASS" if match else "FAIL", source["manufacturer"], t_manufacturer, "Manufacturer preservation (literal display-name comparison)")


@register("IMMUNIZATION.EXPIRATION_DATE", domain=DOMAIN)
def check_expiration_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("expiration_date"):
        return RuleResult("INDETERMINATE", explanation="No source expiration date (RXA-16) supplied")
    raw = source["expiration_date"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no Immunization resource")
    t_exp = target.get("expirationDate", "")
    match = bool(t_exp) and t_exp.replace("-", "") == raw[:8]
    return RuleResult("PASS" if match else "FAIL", raw, t_exp, "Lot expiration date preservation")
