"""Rule pack: patient allergy preservation checks (HL7v2 AL1 -> FHIR
AllergyIntolerance).

Scope: covers scenario-registry.csv SC-041 (allergy substance changed),
SC-042 (reaction lost), SC-043 (severity changed), SC-044 (clinical status
altered), SC-045 (verification status changed), SC-046 (onset date lost).
SC-044/SC-045 rely on an optional ZAL site-defined Z-segment following
AL1 (see `adapters.hl7v2.parse_hl7_allergies`), since real HL7v2 AL1 has
no clinical-status/verification-status field of its own; when ZAL is
absent these checks return INDETERMINATE rather than guessing. SC-047
(negative allergy assertion changed), SC-048 (allergy duplicated), SC-049
(reaction linked to wrong substance), and SC-050 (allergy omitted) are
handled (or out of scope) at the reconciliation-engine level, not here:
SC-048/SC-050 are covered by `compare_many_allergies()`'s
duplicate/missing detection, while SC-047 and SC-049 require cross-record
matching/merge-history context that a single allergy-pair comparison
cannot determine.

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "allergy"

# HL7v2 Table 0128 (Allergy Severity, subset) -> FHIR AllergyIntolerance.reaction.severity.
_SEVERITY_MAP = {"SV": "severe", "MO": "moderate", "MI": "mild"}

# ZAL-1 (site-defined, see adapters.hl7v2) -> FHIR AllergyIntolerance.clinicalStatus code
# (http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical).
_CLINICAL_STATUS_MAP = {"A": "active", "I": "inactive", "R": "resolved"}

# ZAL-2 (site-defined) -> FHIR AllergyIntolerance.verificationStatus code
# (http://terminology.hl7.org/CodeSystem/allergyintolerance-verification).
_VERIFICATION_STATUS_MAP = {"U": "unconfirmed", "C": "confirmed", "F": "refuted", "E": "entered-in-error"}


def _allergen_codes(target: dict) -> list:
    coding = target.get("code", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


def _reaction_manifestations(target: dict) -> list:
    reactions = target.get("reaction", [])
    texts = []
    for r in reactions:
        for m in r.get("manifestation", []):
            if m.get("text"):
                texts.append(m["text"])
            for c in m.get("coding", []):
                if c.get("display"):
                    texts.append(c["display"])
    return texts


@register("ALLERGY.CODE", domain=DOMAIN)
def check_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source allergen code supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no AllergyIntolerance resource")
    codes = _allergen_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Allergen code preservation")


@register("ALLERGY.REACTION", domain=DOMAIN)
def check_reaction(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("reactions"):
        return RuleResult("INDETERMINATE", explanation="No source reaction(s) supplied")
    if not target:
        return RuleResult("FAIL", source["reactions"], "", "Target has no AllergyIntolerance resource")
    manifestations = _reaction_manifestations(target)
    match = all(r in manifestations for r in source["reactions"])
    return RuleResult("PASS" if match else "FAIL", source["reactions"], manifestations,
                       "Reaction manifestation preservation (literal comparison only)")


@register("ALLERGY.SEVERITY", domain=DOMAIN)
def check_severity(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("severity"):
        return RuleResult("INDETERMINATE", explanation="No source severity (AL1-4) supplied")
    expected = _SEVERITY_MAP.get(source["severity"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source severity code '{source['severity']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no AllergyIntolerance resource")
    reactions = target.get("reaction", [])
    severities = [r.get("severity", "") for r in reactions]
    match = expected in severities
    return RuleResult("PASS" if match else "FAIL", expected, severities, "Allergy severity preservation")


@register("ALLERGY.CLINICAL_STATUS", domain=DOMAIN)
def check_clinical_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("clinical_status"):
        return RuleResult("INDETERMINATE", explanation="No source clinical status (ZAL-1) supplied")
    expected = _CLINICAL_STATUS_MAP.get(source["clinical_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source clinical status code '{source['clinical_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no AllergyIntolerance resource")
    codes = [c.get("code", "") for c in target.get("clinicalStatus", {}).get("coding", [])]
    match = expected in codes
    return RuleResult("PASS" if match else "FAIL", expected, codes, "Clinical status preservation")


@register("ALLERGY.VERIFICATION_STATUS", domain=DOMAIN)
def check_verification_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("verification_status"):
        return RuleResult("INDETERMINATE", explanation="No source verification status (ZAL-2) supplied")
    expected = _VERIFICATION_STATUS_MAP.get(source["verification_status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source verification status code '{source['verification_status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no AllergyIntolerance resource")
    codes = [c.get("code", "") for c in target.get("verificationStatus", {}).get("coding", [])]
    match = expected in codes
    return RuleResult("PASS" if match else "FAIL", expected, codes, "Verification status preservation")


@register("ALLERGY.ONSET_DATE", domain=DOMAIN)
def check_onset_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("identification_date"):
        return RuleResult("INDETERMINATE", explanation="No source identification date (AL1-6) supplied")
    raw = source["identification_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source identification date not in supported YYYYMMDD format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no AllergyIntolerance resource")
    actual = (target.get("onsetDateTime") or target.get("recordedDate") or "")[:10]
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual,
                       "Onset/identification date preservation (date-level comparison, onsetDateTime or recordedDate)")
