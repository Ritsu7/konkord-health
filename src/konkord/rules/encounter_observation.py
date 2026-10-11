"""Rule pack: encounter preservation checks (HL7v2 PV1 -> FHIR Encounter).

Scope: covers scenario-registry.csv SC-021 (encounter reference changed),
SC-022 (encounter time altered), SC-023 (encounter class changed), SC-025
(location lost), and SC-026 (attending provider changed). SC-029 (duplicate
encounter) is covered by `reconciliation.engine.compare_batch()` instead,
since it is a cross-record check (a matched target Patient with more than
one Encounter resource), not a single encounter-pair comparison. SC-024
(wrong encounter association), SC-027 (encounter status changed -- HL7v2
PV1 has no direct status-code equivalent to FHIR Encounter.status), SC-028
(ADT event missing), and SC-030 (condition detached from encounter) require
ADT message types or a Condition resource/adapter that do not currently
exist and are out of scope for this rule pack.

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "encounter"

# HL7v2 Table 0004 (Patient Class) -> FHIR Table v3-ActEncounterCode (subset).
_CLASS_MAP = {"I": "IMP", "O": "AMB", "E": "EMER", "P": "PRENC", "R": "ACUTE", "B": "AMB"}


@register("ENCOUNTER.CLASS", domain=DOMAIN)
def check_class(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("patient_class"):
        return RuleResult("INDETERMINATE", explanation="No source patient class (PV1-2) supplied")
    expected = _CLASS_MAP.get(source["patient_class"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source patient class '{source['patient_class']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Encounter resource")
    actual = target.get("class", {}).get("code", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Encounter class preservation")


@register("ENCOUNTER.LOCATION", domain=DOMAIN)
def check_location(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("location"):
        return RuleResult("INDETERMINATE", explanation="No source location (PV1-3) supplied")
    if not target:
        return RuleResult("FAIL", source["location"], "", "Target has no Encounter resource")
    locations = [loc.get("location", {}).get("display", "") for loc in target.get("location", [])]
    match = source["location"] in locations
    return RuleResult("PASS" if match else "FAIL", source["location"], locations, "Encounter location preservation")


@register("ENCOUNTER.ATTENDING", domain=DOMAIN)
def check_attending(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("attending_id"):
        return RuleResult("INDETERMINATE", explanation="No source attending provider (PV1-7) supplied")
    if not target:
        return RuleResult("FAIL", source["attending_id"], "", "Target has no Encounter resource")
    participants = [
        p.get("individual", {}).get("reference", "")
        for p in target.get("participant", [])
        if any(c.get("code") == "ATND" for c in p.get("type", [{}])[0].get("coding", []))
    ] if target.get("participant") else []
    match = any(source["attending_id"] in ref for ref in participants)
    return RuleResult("PASS" if match else "FAIL", source["attending_id"], participants,
                       "Attending provider preservation (substring match on participant.individual.reference)")


@register("ENCOUNTER.PERIOD_START", domain=DOMAIN)
def check_period_start(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("admit_datetime"):
        return RuleResult("INDETERMINATE", explanation="No source admit date/time (PV1-44) supplied")
    raw = source["admit_datetime"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no Encounter resource")
    start = target.get("period", {}).get("start", "")
    match = bool(start) and start.replace("-", "").replace(":", "").startswith(raw[:8])
    return RuleResult("PASS" if match else "FAIL", raw, start, "Encounter admit time preservation (date-level comparison)")
