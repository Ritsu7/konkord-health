"""Rule pack: insurance coverage preservation checks (HL7v2 IN1 -> FHIR
Coverage).

Scope: covers scenario-registry.csv SC-061 (effective date changed),
SC-062 (termination date changed), SC-063 (subscriber relationship
changed), SC-064 (member ID altered), SC-066 (payor reference changed),
SC-067 (group number lost), SC-068 (coverage status changed), and SC-070
(coverage priority changed). SC-065 (beneficiary changed) and SC-069
(duplicate coverage) are handled at the reconciliation-engine level, not
here (they need cross-record/batch context, mirroring PATIENT.REFERENCE
and ENCOUNTER.DUPLICATE). SC-068 relies on an optional ZIN site-defined
Z-segment following IN1 (see `adapters.hl7v2.parse_hl7_coverage`), since
real HL7v2.5 IN1 has no coverage-status field of its own (no analog to
FHIR Coverage.status: active/cancelled/draft/entered-in-error); when ZIN
is absent this check returns INDETERMINATE rather than guessing.

Like the other rule packs, checks are deterministic and never guess
clinical/business equivalence; insufficient evidence returns
INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "coverage"

# ZIN-1 (site-defined, see adapters.hl7v2) -> FHIR Coverage.status.
_STATUS_MAP = {"AC": "active", "CA": "cancelled", "DR": "draft", "EE": "entered-in-error"}


def _payor_ids(target: dict) -> list:
    return [ref.get("reference", "").split("/")[-1] for ref in target.get("payor", []) if ref.get("reference")]


def _group_number(target: dict) -> str:
    for klass in target.get("class", []):
        coding = klass.get("type", {}).get("coding", [])
        if any(c.get("code") == "group" for c in coding):
            return klass.get("value", "")
    return ""


@register("COVERAGE.EFFECTIVE_DATE", domain=DOMAIN)
def check_effective_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("effective_date"):
        return RuleResult("INDETERMINATE", explanation="No source plan effective date (IN1-12) supplied")
    raw = source["effective_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source effective date not in supported YYYYMMDD... format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Coverage resource")
    actual = (target.get("period", {}).get("start") or "")[:10]
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual,
                       "Coverage effective date preservation (date-level comparison)")


@register("COVERAGE.EXPIRATION_DATE", domain=DOMAIN)
def check_expiration_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("expiration_date"):
        return RuleResult("INDETERMINATE", explanation="No source plan expiration date (IN1-13) supplied")
    raw = source["expiration_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source expiration date not in supported YYYYMMDD... format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Coverage resource")
    actual = (target.get("period", {}).get("end") or "")[:10]
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual,
                       "Coverage termination date preservation (date-level comparison)")


@register("COVERAGE.RELATIONSHIP", domain=DOMAIN)
def check_relationship(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("relationship"):
        return RuleResult("INDETERMINATE", explanation="No source subscriber relationship (IN1-17) supplied")
    if not target:
        return RuleResult("FAIL", source["relationship"], "", "Target has no Coverage resource")
    coding = target.get("relationship", {}).get("coding", [])
    codes = [c.get("code", "") for c in coding]
    match = source["relationship"] in codes
    return RuleResult("PASS" if match else "FAIL", source["relationship"], codes,
                       "Subscriber relationship preservation")


@register("COVERAGE.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="No source coverage status (ZIN-1) supplied")
    expected = _STATUS_MAP.get(source["status"])
    if expected is None:
        return RuleResult("INDETERMINATE", explanation=f"Unsupported source coverage status code '{source['status']}'")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Coverage resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Coverage status preservation")


@register("COVERAGE.MEMBER_ID", domain=DOMAIN)
def check_member_id(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("member_id"):
        return RuleResult("INDETERMINATE", explanation="No source member ID (IN1-49) supplied")
    if not target:
        return RuleResult("FAIL", source["member_id"], "", "Target has no Coverage resource")
    actual = target.get("subscriberId", "")
    return RuleResult("PASS" if source["member_id"] == actual else "FAIL", source["member_id"], actual,
                       "Member ID preservation (IN1-49 vs Coverage.subscriberId)")


@register("COVERAGE.PAYOR_REFERENCE", domain=DOMAIN)
def check_payor_reference(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("payor_id"):
        return RuleResult("INDETERMINATE", explanation="No source insurance company ID (IN1-3) supplied")
    if not target:
        return RuleResult("FAIL", source["payor_id"], "", "Target has no Coverage resource")
    payor_ids = _payor_ids(target)
    match = source["payor_id"] in payor_ids
    return RuleResult("PASS" if match else "FAIL", source["payor_id"], payor_ids, "Payor reference preservation")


@register("COVERAGE.GROUP_NUMBER", domain=DOMAIN)
def check_group_number(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("group_number"):
        return RuleResult("INDETERMINATE", explanation="No source group number (IN1-8) supplied")
    if not target:
        return RuleResult("FAIL", source["group_number"], "", "Target has no Coverage resource")
    actual = _group_number(target)
    return RuleResult("PASS" if source["group_number"] == actual else "FAIL", source["group_number"], actual,
                       "Group number preservation (IN1-8 vs Coverage.class[type=group].value)")


@register("COVERAGE.PRIORITY", domain=DOMAIN)
def check_priority(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("cob_priority"):
        return RuleResult("INDETERMINATE", explanation="No source coordination-of-benefits priority (IN1-22) supplied")
    if not target:
        return RuleResult("FAIL", source["cob_priority"], "", "Target has no Coverage resource")
    actual = target.get("order", "")
    match = str(actual) == str(source["cob_priority"])
    return RuleResult("PASS" if match else "FAIL", source["cob_priority"], actual,
                       "Coverage priority preservation (IN1-22 COB priority vs Coverage.order)")
