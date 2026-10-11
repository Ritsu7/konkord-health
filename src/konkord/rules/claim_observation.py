"""Rule pack: claim adjudication preservation checks (FHIR Claim submission
-> FHIR ExplanationOfBenefit adjudication).

Scope: like Prior Authorization, this is a FHIR-to-FHIR domain -- there is
no HL7v2 analog for a professional/institutional claim submission (the
real-world wire format is X12 837/835, which Konkord does not parse), so
"source" is modeled as a FHIR Claim (use="claim", the request as
submitted) and "target" as the corresponding FHIR ExplanationOfBenefit
(the payer's adjudication).

Covers scenario-registry.csv SC-082 (billed amount changed), SC-083
(currency altered), SC-084 (diagnosis linkage lost), and SC-088
(adjudication status altered). SC-081 (claim line omitted), SC-085
(service date changed), SC-086 (procedure code changed), SC-087 (service
quantity changed), and SC-090 (claim/EOB link mismatched) are handled at
the reconciliation-engine level, not here (they need the full list of
claim items, not a single-field comparison).

SC-089 (payment adjustment omitted) is out of scope: `EOB.payment` is
purely payer-adjudication data with no analog on the submitted Claim to
compare against -- there is nothing to reconcile, only to inspect.

Like the other rule packs, checks are deterministic and never guess
clinical/business equivalence; insufficient evidence returns
INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "claim"


def _total_amount(resource: dict, category_code: str | None = None) -> dict:
    """Claim.total is a single Money; EOB.total is a list of {category,
    amount} entries. Normalize both to a single Money dict, preferring the
    'submitted' category entry on EOB.total when present.
    """
    total = resource.get("total")
    if isinstance(total, dict):
        return total
    if isinstance(total, list):
        for entry in total:
            codes = [c.get("code", "") for c in entry.get("category", {}).get("coding", [])]
            if category_code is None or category_code in codes:
                return entry.get("amount", {})
        if total:
            return total[0].get("amount", {})
    return {}


@register("CLAIM.STATUS", domain=DOMAIN)
def check_status(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("status"):
        return RuleResult("INDETERMINATE", explanation="Source Claim has no status")
    if not target:
        return RuleResult("FAIL", source["status"], "", "Target has no ExplanationOfBenefit resource")
    actual = target.get("status", "")
    return RuleResult("PASS" if source["status"] == actual else "FAIL", source["status"], actual,
                       "Claim resource status preservation (Claim.status vs ExplanationOfBenefit.status)")


@register("CLAIM.BILLED_AMOUNT", domain=DOMAIN)
def check_billed_amount(source: dict, target: dict) -> RuleResult:
    billed = _total_amount(source) if source else {}
    if billed.get("value") is None:
        return RuleResult("INDETERMINATE", explanation="Source Claim has no total billed amount")
    if not target:
        return RuleResult("FAIL", billed.get("value"), "", "Target has no ExplanationOfBenefit resource")
    submitted = _total_amount(target, "submitted")
    actual = submitted.get("value")
    match = actual is not None and float(billed["value"]) == float(actual)
    return RuleResult("PASS" if match else "FAIL", billed.get("value"), actual,
                       "Billed amount preservation (Claim.total vs ExplanationOfBenefit "
                       "total[category=submitted].amount)")


@register("CLAIM.CURRENCY", domain=DOMAIN)
def check_currency(source: dict, target: dict) -> RuleResult:
    billed = _total_amount(source) if source else {}
    currency = billed.get("currency")
    if not currency:
        return RuleResult("INDETERMINATE", explanation="Source Claim total has no currency")
    if not target:
        return RuleResult("FAIL", currency, "", "Target has no ExplanationOfBenefit resource")
    submitted = _total_amount(target, "submitted")
    actual = submitted.get("currency", "")
    return RuleResult("PASS" if currency == actual else "FAIL", currency, actual,
                       "Currency preservation (Claim.total.currency vs ExplanationOfBenefit "
                       "total[category=submitted].amount.currency)")


@register("CLAIM.DIAGNOSIS_LINKAGE", domain=DOMAIN)
def check_diagnosis_linkage(source: dict, target: dict) -> RuleResult:
    diagnoses = source.get("diagnosis", []) if source else []
    if not diagnoses:
        return RuleResult("INDETERMINATE", explanation="Source Claim has no diagnosis entries")

    def _key(d: dict) -> tuple:
        coding = d.get("diagnosisCodeableConcept", {}).get("coding", [])
        code = coding[0].get("code", "") if coding else ""
        return (d.get("sequence"), code)

    expected = {_key(d) for d in diagnoses}
    if not target:
        return RuleResult("FAIL", sorted(expected), [], "Target has no ExplanationOfBenefit resource")
    actual = {_key(d) for d in target.get("diagnosis", [])}
    match = expected.issubset(actual)
    return RuleResult("PASS" if match else "FAIL", sorted(expected), sorted(actual),
                       "Diagnosis linkage preservation (Claim.diagnosis[] sequence+code vs "
                       "ExplanationOfBenefit.diagnosis[])")
