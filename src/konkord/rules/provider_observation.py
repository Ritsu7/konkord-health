"""Rule pack: Da Vinci PDex Plan-Net provider directory preservation
checks (credentialing-system PractitionerRole -> published-directory
PractitionerRole).

Scope: covers scenario-registry.csv SC-121 (NPI mismatch), SC-122
(network participation status stale), SC-124 (accepting-new-patients
flag out of date), SC-125 (specialty/taxonomy code dropped), and SC-129
(provider terminated but still listed active). SC-123 (practice address
changed), SC-126 (provider duplicated under two organizations), SC-127
(telehealth/service location omitted), SC-128 (health plan/network
reference broken), and SC-130 (phone/contact drift) are handled at the
reconciliation-engine level, not here, since they need cross-entry or
whole-batch context (mirroring other domains' MISSING/DUPLICATE-style
checks), not a single matched-pair field comparison.

Each rule here operates on one matched pair of "directory entry" dicts,
as produced by adapters.fhir.parse_fhir_provider_directory_bundle():
{"role": PractitionerRole dict, "practitioner": Practitioner dict | None,
 "locations": [Location dict, ...], "healthcare_services": [...]}.

Like the other rule packs, checks are deterministic and never guess
clinical/business equivalence; insufficient evidence returns
INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "provider"

_NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"
_NEW_PATIENTS_EXT_URL = "http://hl7.org/fhir/us/davinci-pdex-plan-net/StructureDefinition/newpatients"


def _npi_of(practitioner: dict | None) -> str:
    if not practitioner:
        return ""
    for ident in practitioner.get("identifier", []):
        if ident.get("system") == _NPI_SYSTEM:
            return ident.get("value", "")
    return ""


def _accepting_patients_code(role: dict) -> str:
    for ext in role.get("extension", []):
        if ext.get("url") == _NEW_PATIENTS_EXT_URL:
            for sub in ext.get("extension", []):
                if sub.get("url") == "acceptingPatients":
                    codings = sub.get("valueCodeableConcept", {}).get("coding", [])
                    if codings:
                        return codings[0].get("code", "")
    return ""


def _specialty_codes(role: dict) -> list:
    return [c.get("code", "") for sc in role.get("specialty", []) for c in sc.get("coding", [])]


@register("PROVIDER.NPI", domain=DOMAIN)
def check_npi(source: dict, target: dict) -> RuleResult:
    source_npi = _npi_of((source or {}).get("practitioner"))
    if not source_npi:
        return RuleResult("INDETERMINATE", explanation="No source Practitioner NPI (identifier) supplied")
    if not target or not target.get("role"):
        return RuleResult("FAIL", source_npi, "", "Target has no matching PractitionerRole entry")
    target_npi = _npi_of(target.get("practitioner"))
    return RuleResult("PASS" if source_npi == target_npi else "FAIL", source_npi, target_npi,
                       "NPI preservation (Practitioner.identifier[system=us-npi].value)")


@register("PROVIDER.NETWORK_STATUS", domain=DOMAIN)
def check_network_status(source: dict, target: dict) -> RuleResult:
    source_role = (source or {}).get("role") or {}
    if "active" not in source_role:
        return RuleResult("INDETERMINATE", explanation="No source PractitionerRole.active flag supplied")
    if not target or not target.get("role"):
        return RuleResult("FAIL", source_role.get("active"), "", "Target has no matching PractitionerRole entry")
    target_active = target["role"].get("active")
    match = source_role.get("active") == target_active
    return RuleResult("PASS" if match else "FAIL", source_role.get("active"), target_active,
                       "Network participation status preservation (PractitionerRole.active)")


@register("PROVIDER.NEW_PATIENTS", domain=DOMAIN)
def check_new_patients(source: dict, target: dict) -> RuleResult:
    source_role = (source or {}).get("role") or {}
    source_code = _accepting_patients_code(source_role)
    if not source_code:
        return RuleResult("INDETERMINATE", explanation="No source accepting-new-patients extension supplied")
    if not target or not target.get("role"):
        return RuleResult("FAIL", source_code, "", "Target has no matching PractitionerRole entry")
    target_code = _accepting_patients_code(target["role"])
    return RuleResult("PASS" if source_code == target_code else "FAIL", source_code, target_code,
                       "Accepting-new-patients preservation (PractitionerRole.extension[newpatients]"
                       ".acceptingPatients)")


@register("PROVIDER.SPECIALTY", domain=DOMAIN)
def check_specialty(source: dict, target: dict) -> RuleResult:
    source_codes = _specialty_codes((source or {}).get("role") or {})
    if not source_codes:
        return RuleResult("INDETERMINATE", explanation="No source PractitionerRole.specialty codes supplied")
    if not target or not target.get("role"):
        return RuleResult("FAIL", source_codes, "", "Target has no matching PractitionerRole entry")
    target_codes = _specialty_codes(target["role"])
    match = set(source_codes).issubset(set(target_codes))
    return RuleResult("PASS" if match else "FAIL", source_codes, target_codes,
                       "Specialty/taxonomy preservation (PractitionerRole.specialty[].coding[].code)")


@register("PROVIDER.TERMINATION", domain=DOMAIN)
def check_termination(source: dict, target: dict) -> RuleResult:
    source_role = (source or {}).get("role") or {}
    period_end = source_role.get("period", {}).get("end", "")
    if not period_end:
        return RuleResult("INDETERMINATE", explanation="No source PractitionerRole.period.end supplied")
    if not target or not target.get("role"):
        return RuleResult("FAIL", period_end, "", "Target has no matching PractitionerRole entry")
    target_active = target["role"].get("active")
    match = target_active is False
    return RuleResult("PASS" if match else "FAIL", f"terminated {period_end}", target_active,
                       "A PractitionerRole with a past period.end (terminated) must not remain "
                       "active=true in the published directory")
