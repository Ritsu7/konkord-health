"""Rule pack: diagnosis/condition preservation checks (HL7v2 DG1 -> FHIR
Condition).

Scope: covers scenario-registry.csv SC-051 (diagnosis code changed),
SC-052 (condition clinical status changed), SC-053 (verification status
changed), and SC-054 (onset date lost). SC-052/SC-053 rely on an optional
ZDG site-defined Z-segment following DG1 (see
`adapters.hl7v2.parse_hl7_conditions`), since real HL7v2.5 DG1 has no
clinical-status/verification-status field of its own (the same limitation
documented for AL1/allergy clinical/verification status); when ZDG is
absent these checks return INDETERMINATE rather than guessing. SC-060
(diagnosis encounter relationship lost) is handled at the
reconciliation-engine level, not here, via a batch-wide encounter
reference consistency check (mirrors PATIENT.REFERENCE).

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "condition"

# ZDG-1 (site-defined, see adapters.hl7v2) -> FHIR Condition.clinicalStatus code
# (http://terminology.hl7.org/CodeSystem/condition-clinical).
_CLINICAL_STATUS_MAP = {"A": "active", "I": "inactive", "R": "resolved"}

# ZDG-2 (site-defined) -> FHIR Condition.verificationStatus code
# (http://terminology.hl7.org/CodeSystem/condition-ver-status).
_VERIFICATION_STATUS_MAP = {"U": "unconfirmed", "C": "confirmed", "F": "refuted", "E": "entered-in-error"}


def _condition_codes(target: dict) -> list:
    coding = target.get("code", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


@register("CONDITION.CODE", domain=DOMAIN)
def check_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source diagnosis code (DG1-3) supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no Condition resource")
    codes = _condition_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Diagnosis code preservation")


@register("CONDITION.CLINICAL_STATUS", domain=DOMAIN)
def check_clinical_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("clinical_status"):
        return RuleResult("INDETERMINATE", explanation="No source clinical status (ZDG-1) supplied")
    expected = _CLINICAL_STATUS_MAP.get(source["clinical_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source clinical status code '{source['clinical_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Condition resource")
    codes = [c.get("code", "") for c in target.get("clinicalStatus", {}).get("coding", [])]
    match = expected in codes
    return RuleResult("PASS" if match else "FAIL", expected, codes, "Clinical status preservation")


@register("CONDITION.VERIFICATION_STATUS", domain=DOMAIN)
def check_verification_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("verification_status"):
        return RuleResult("INDETERMINATE", explanation="No source verification status (ZDG-2) supplied")
    expected = _VERIFICATION_STATUS_MAP.get(source["verification_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source verification status code '{source['verification_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Condition resource")
    codes = [c.get("code", "") for c in target.get("verificationStatus", {}).get("coding", [])]
    match = expected in codes
    return RuleResult("PASS" if match else "FAIL", expected, codes, "Verification status preservation")


@register("CONDITION.ONSET_DATE", domain=DOMAIN)
def check_onset_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("onset_date"):
        return RuleResult("INDETERMINATE", explanation="No source diagnosis date/time (DG1-5) supplied")
    raw = source["onset_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source diagnosis date not in supported YYYYMMDD... format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Condition resource")
    actual = (target.get("onsetDateTime") or target.get("recordedDate") or "")[:10]
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual,
                       "Onset/diagnosis date preservation (date-level comparison, onsetDateTime or recordedDate)")
