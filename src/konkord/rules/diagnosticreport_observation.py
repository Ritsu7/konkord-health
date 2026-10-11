"""Rule pack: diagnostic report preservation checks (HL7v2 ORU^R01 OBR
header -> FHIR R4B DiagnosticReport, per the US Core Laboratory Result
profile).

Scope: covers scenario-registry.csv SC-167 (result status silently
regressed, e.g. a corrected/final report re-reported as preliminary),
SC-168 (universal service code altered), SC-169 (report date changed),
SC-173 (principal result interpreter dropped). This is distinct from the
existing Laboratory domain (`lab_observation`),
which diffs individual OBX result values against FHIR Observation; this
rule pack instead diffs the OBR *report header* against FHIR
DiagnosticReport, which `adapters.hl7v2.parse_hl7_oru`/`parse_hl7_oru_batch`
never surface (they only use OBR-15 for OBX specimen-type grouping).

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "diagnosticreport"

# HL7v2 Table 0123 (Result Status, subset) -> FHIR DiagnosticReport.status.
_STATUS_MAP = {"P": "preliminary", "F": "final", "C": "corrected", "X": "cancelled"}


def _report_codes(target: dict) -> list:
    coding = target.get("code", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


@register("DIAGNOSTICREPORT.CODE", domain=DOMAIN)
def check_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source universal service identifier (OBR-4) supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no DiagnosticReport resource")
    codes = _report_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Universal service (LOINC) code preservation")


@register("DIAGNOSTICREPORT.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("result_status"):
        return RuleResult("INDETERMINATE", explanation="No source result status (OBR-25) supplied")
    expected = _STATUS_MAP.get(source["result_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source result status '{source['result_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no DiagnosticReport resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Result status preservation")


@register("DIAGNOSTICREPORT.EFFECTIVE_DATE", domain=DOMAIN)
def check_effective_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("date"):
        return RuleResult("INDETERMINATE", explanation="No source observation date/time (OBR-7) supplied")
    raw = source["date"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no DiagnosticReport resource")
    effective = target.get("effectiveDateTime", "") or target.get("effectivePeriod", {}).get("start", "")
    match = bool(effective) and effective.replace("-", "").replace(":", "").startswith(raw[:8])
    return RuleResult("PASS" if match else "FAIL", raw, effective, "Report date preservation (date-level comparison)")


@register("DIAGNOSTICREPORT.PERFORMER", domain=DOMAIN)
def check_performer(source: dict, target: dict) -> RuleResult:
    """OBR-32 (Principal Result Interpreter, CNN) vs
    DiagnosticReport.performer[].reference.

    US Core Laboratory Result Diagnostic Report profile marks
    DiagnosticReport.performer as Must Support; dropping it during HL7v2-to-
    FHIR translation is a real, spec-relevant defect class, not a
    hypothetical.
    """
    if not source or not source.get("performer_id"):
        return RuleResult("INDETERMINATE", explanation="No source principal result interpreter supplied (OBR-32)")
    if not target:
        return RuleResult("FAIL", source["performer_id"], "", "Target has no DiagnosticReport resource")
    performer = source["performer_id"]
    refs = [p.get("reference", "") for p in target.get("performer", [])]
    match = any(performer in ref for ref in refs)
    return RuleResult("PASS" if match else "FAIL", performer, refs,
                       "Principal result interpreter preservation (OBR-32 vs DiagnosticReport.performer[].reference, substring match)")
