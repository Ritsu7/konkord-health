"""Rule pack: patient identity preservation checks (HL7v2 PID -> FHIR Patient).

Scope: covers scenario-registry.csv SC-012 (MRN lost), SC-013 (assigning
authority changed), SC-016 (birth date changed), SC-017 (deceased flag lost),
and SC-018 (demographic/name mapping altered). All other Identity scenarios
(SC-011, SC-014, SC-015, SC-019, SC-020) remain PLANNED; they require
cross-record matching/merge-history context that a single patient-pair
comparison cannot determine and are out of scope for this rule pack.

Like lab_observation.py, these checks are deterministic and never guess
clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "patient"


def _identifiers(target: dict) -> list:
    return target.get("identifier", []) if target else []


def _mrn_values(target: dict) -> list:
    values = []
    for ident in _identifiers(target):
        codes = [c.get("code") for c in ident.get("type", {}).get("coding", [])]
        if "MR" in codes:
            values.append(ident.get("value", ""))
    return values


@register("IDENTITY.MRN", domain=DOMAIN)
def check_mrn(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("id"):
        return RuleResult("INDETERMINATE", explanation="No source MRN supplied")
    if not target:
        return RuleResult("FAIL", source["id"], "", "Target has no Patient resource")
    mrns = _mrn_values(target)
    match = source["id"] in mrns
    return RuleResult("PASS" if match else "FAIL", source["id"], mrns, "Medical record number preservation")


@register("IDENTITY.ASSIGNING_AUTHORITY", domain=DOMAIN)
def check_assigning_authority(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("assigning_authority"):
        return RuleResult("INDETERMINATE", explanation="No source assigning authority supplied")
    if not target:
        return RuleResult("FAIL", source["assigning_authority"], "", "Target has no Patient resource")
    systems = [ident.get("system", "") for ident in _identifiers(target)]
    match = any(source["assigning_authority"] in sys_ for sys_ in systems)
    return RuleResult("PASS" if match else "FAIL", source["assigning_authority"], systems,
                       "Identifier assigning authority preservation (substring match on identifier.system)")


@register("IDENTITY.BIRTH_DATE", domain=DOMAIN)
def check_birth_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("birth_date"):
        return RuleResult("INDETERMINATE", explanation="No source birth date supplied")
    raw = source["birth_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source birth date not in supported YYYYMMDD format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Patient resource")
    actual = target.get("birthDate", "")
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual, "Birth date preservation")


@register("IDENTITY.DECEASED", domain=DOMAIN)
def check_deceased(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("deceased_indicator"):
        return RuleResult("INDETERMINATE", explanation="No source deceased indicator supplied")
    source_deceased = source["deceased_indicator"] in ("Y", "y", "1")
    if not source_deceased:
        return RuleResult("INDETERMINATE", explanation="Source does not assert patient is deceased")
    if not target:
        return RuleResult("FAIL", "deceased", "", "Target has no Patient resource")
    target_deceased = bool(target.get("deceasedDateTime")) or target.get("deceasedBoolean") is True
    return RuleResult("PASS" if target_deceased else "FAIL", "deceased",
                       "deceased" if target_deceased else "not deceased", "Deceased flag preservation")


@register("IDENTITY.NAME", domain=DOMAIN)
def check_name(source: dict, target: dict) -> RuleResult:
    if not source or not (source.get("family_name") or source.get("given_name")):
        return RuleResult("INDETERMINATE", explanation="No source patient name supplied")
    if not target:
        return RuleResult("FAIL", source.get("family_name", ""), "", "Target has no Patient resource")
    names = target.get("name", [])
    families = [n.get("family", "") for n in names]
    match = bool(source.get("family_name")) and source["family_name"] in families
    return RuleResult("PASS" if match else "FAIL", source.get("family_name", ""), families,
                       "Family name preservation (literal comparison only)")
