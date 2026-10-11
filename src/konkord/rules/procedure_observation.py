"""Rule pack: procedure preservation checks (HL7v2 PR1[/ROL] -> FHIR
Procedure).

Scope: covers scenario-registry.csv SC-055 (procedure status altered),
SC-056 (procedure performer changed), and SC-057 (procedure date changed).
SC-055 relies on an optional ZPR site-defined Z-segment following PR1
(see `adapters.hl7v2.parse_hl7_procedures`), since real HL7v2.5 PR1 has
no procedure-status field of its own (no analog to FHIR Procedure.status:
preparation/in-progress/completed/stopped); when ZPR is absent this check
returns INDETERMINATE rather than guessing.

Like the other rule packs, checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "procedure"

# ZPR-1 (site-defined, see adapters.hl7v2) -> FHIR Procedure.status.
_STATUS_MAP = {"PR": "preparation", "IP": "in-progress", "CM": "completed", "SP": "stopped"}


def _procedure_codes(target: dict) -> list:
    coding = target.get("code", {}).get("coding", [])
    return [c.get("code", "") for c in coding]


def _performer_ids(target: dict) -> list:
    performers = target.get("performer", [])
    ids = []
    for p in performers:
        ref = p.get("actor", {}).get("reference", "")
        if ref:
            ids.append(ref.split("/")[-1])
    return ids


@register("PROCEDURE.CODE", domain=DOMAIN)
def check_code(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source procedure code (PR1-3) supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no Procedure resource")
    codes = _procedure_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "Procedure code preservation")


@register("PROCEDURE.PERFORMER", domain=DOMAIN)
def check_performer(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("performer"):
        return RuleResult("INDETERMINATE", explanation="No source performer (PR1-11/ROL-4) supplied")
    if not target:
        return RuleResult("FAIL", source["performer"], "", "Target has no Procedure resource")
    performers = _performer_ids(target)
    match = source["performer"] in performers
    return RuleResult("PASS" if match else "FAIL", source["performer"], performers, "Procedure performer preservation")


@register("PROCEDURE.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="No source procedure status (ZPR-1) supplied")
    expected = _STATUS_MAP.get(source["status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source procedure status code '{source['status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Procedure resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Procedure status preservation")


@register("PROCEDURE.DATE", domain=DOMAIN)
def check_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("date"):
        return RuleResult("INDETERMINATE", explanation="No source procedure date/time (PR1-5) supplied")
    raw = source["date"]
    if not target:
        return RuleResult("FAIL", raw, "", "Target has no Procedure resource")
    performed = target.get("performedDateTime", "") or target.get("performedPeriod", {}).get("start", "")
    match = bool(performed) and performed.replace("-", "").replace(":", "").startswith(raw[:8])
    return RuleResult("PASS" if match else "FAIL", raw, performed, "Procedure date preservation (date-level comparison)")
