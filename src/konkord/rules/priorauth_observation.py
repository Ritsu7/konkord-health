"""Rule pack: prior-authorization preservation checks (FHIR Claim request
-> FHIR ClaimResponse decision).

Scope: this is Konkord's only FHIR-to-FHIR domain. There is no HL7v2
analog for a prior-authorization request (the real-world wire format is
X12 278, which Konkord does not parse), so "source" is itself modeled as
a FHIR Claim (the request as submitted) and "target" as the corresponding
FHIR ClaimResponse (the payer's decision) -- both real R4B resources.

Covers scenario-registry.csv SC-071 (authorization status changed),
SC-072 (authorization ID lost), SC-074 (approved quantity changed),
SC-075 (validity period changed), SC-078 (decision reason omitted), and
SC-080 (workflow status desynchronized). SC-077 (requested vs approved
service mismatch) and SC-079 (coverage link lost) are handled at the
reconciliation-engine level, not here (they need the full list of claim
items/insurance entries, not a single-field comparison).

SC-073 (service code altered) and SC-076 (supporting information
omitted) are out of scope: base FHIR R4B `ClaimResponse.item` has no
`productOrService` element and `ClaimResponse` has no `supportingInfo`
echo, so there is nothing on the target side to compare against.

Like the other rule packs, checks are deterministic and never guess
clinical/business equivalence; insufficient evidence returns
INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "priorauth"


def _first_identifier(resource: dict) -> str:
    identifiers = resource.get("identifier", [])
    return identifiers[0].get("value", "") if identifiers else ""


@register("PRIORAUTH.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="Source Claim has no status")
    if not target:
        return RuleResult("FAIL", source["status"], "", "Target has no ClaimResponse resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if source["status"] == actual else "FAIL", source["status"], actual,
                       "Authorization resource status preservation (Claim.status vs ClaimResponse.status)")


@register("PRIORAUTH.AUTHORIZATION_ID", domain=DOMAIN)
def check_authorization_id(source: dict, target: dict) -> RuleResult:
    source_id = _first_identifier(source) if source else ""
    if not source_id:
        return RuleResult("INDETERMINATE", explanation="Source Claim has no identifier")
    if not target:
        return RuleResult("FAIL", source_id, "", "Target has no ClaimResponse resource")
    actual = _first_identifier(target)
    return RuleResult("PASS" if source_id == actual else "FAIL", source_id, actual,
                       "Authorization ID preservation (Claim.identifier vs ClaimResponse.identifier)")


@register("PRIORAUTH.APPROVED_QUANTITY", domain=DOMAIN)
def check_approved_quantity(source: dict, target: dict) -> RuleResult:
    items = source.get("item", []) if source else []
    requested = items[0].get("quantity", {}).get("value") if items else None
    if requested is None:
        return RuleResult("INDETERMINATE", explanation="Source Claim item has no requested quantity")
    if not target:
        return RuleResult("FAIL", requested, "", "Target has no ClaimResponse resource")
    adjudications = (target.get("item", [{}])[0].get("adjudication", []) if target.get("item") else [])
    approved = None
    for adj in adjudications:
        codes = [c.get("code", "") for c in adj.get("category", {}).get("coding", [])]
        if "benefit" in codes:
            approved = adj.get("value")
            break
    if approved is None:
        return RuleResult("FAIL", requested, "", "No 'benefit' adjudication entry found on ClaimResponse item")
    return RuleResult("PASS" if float(requested) == float(approved) else "FAIL", requested, approved,
                       "Approved quantity preservation (Claim.item.quantity vs ClaimResponse "
                       "item.adjudication[category=benefit].value)")


@register("PRIORAUTH.VALIDITY_PERIOD", domain=DOMAIN)
def check_validity_period(source: dict, target: dict) -> RuleResult:
    period = source.get("billablePeriod", {}) if source else {}
    if not period:
        return RuleResult("INDETERMINATE", explanation="Source Claim has no billablePeriod")
    if not target:
        return RuleResult("FAIL", period, "", "Target has no ClaimResponse resource")
    actual = target.get("preAuthPeriod", {})
    match = period.get("start") == actual.get("start") and period.get("end") == actual.get("end")
    return RuleResult("PASS" if match else "FAIL", period, actual,
                       "Validity period preservation (Claim.billablePeriod vs ClaimResponse.preAuthPeriod)")


@register("PRIORAUTH.DECISION_REASON", domain=DOMAIN)
def check_decision_reason(source: dict, target: dict) -> RuleResult:
    if not target or not target.get("outcome"):
        return RuleResult("INDETERMINATE", explanation="Target ClaimResponse has no outcome")
    outcome = target["outcome"]
    disposition = target.get("disposition", "")
    if outcome in ("error", "partial") and not disposition:
        return RuleResult("FAIL", "", "", f"ClaimResponse outcome '{outcome}' has no disposition explaining the decision")
    return RuleResult("PASS", outcome, disposition, "Decision reason present for non-complete outcomes")


@register("PRIORAUTH.WORKFLOW_SYNC", domain=DOMAIN)
def check_workflow_sync(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="Source Claim has no status")
    if not target or not target.get("outcome"):
        return RuleResult("INDETERMINATE", explanation="Target ClaimResponse has no outcome")
    status, outcome = source["status"], target["outcome"]
    if status == "cancelled" and outcome == "complete":
        return RuleResult("FAIL", status, outcome,
                           "Claim was cancelled but ClaimResponse outcome is 'complete'; workflow desynchronized")
    return RuleResult("PASS", status, outcome, "Claim status and ClaimResponse outcome are workflow-consistent")
