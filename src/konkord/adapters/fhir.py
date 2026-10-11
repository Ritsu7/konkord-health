"""FHIR R4 adapter.

Scope: loads Bundle/Observation/Patient resources as plain dicts for
comparison. Reconciliation itself stays schema-agnostic (plain dicts), but
`validate_fhir_structure()` below provides real FHIR R4B structural
validation (via the `fhir.resources` library) as a best-effort, non-blocking
check surfaced to callers as warnings -- it does not gate reconciliation,
since Konkord's job is to compare source vs. target as given, not to reject
inputs a real EHR/interface engine would still want reconciled.
"""
from __future__ import annotations
import json
from pathlib import Path

from fhir.resources.R4B.bundle import Bundle as _R4BBundle
from fhir.resources.R4B.observation import Observation as _R4BObservation
from fhir.resources.R4B.patient import Patient as _R4BPatient
from fhir.resources.R4B.encounter import Encounter as _R4BEncounter
from fhir.resources.R4B.medicationrequest import MedicationRequest as _R4BMedicationRequest
from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as _R4BAllergyIntolerance
from fhir.resources.R4B.condition import Condition as _R4BCondition
from fhir.resources.R4B.procedure import Procedure as _R4BProcedure
from fhir.resources.R4B.coverage import Coverage as _R4BCoverage
from fhir.resources.R4B.claim import Claim as _R4BClaim
from fhir.resources.R4B.claimresponse import ClaimResponse as _R4BClaimResponse
from fhir.resources.R4B.explanationofbenefit import ExplanationOfBenefit as _R4BExplanationOfBenefit
from fhir.resources.R4B.documentreference import DocumentReference as _R4BDocumentReference
from fhir.resources.R4B.practitionerrole import PractitionerRole as _R4BPractitionerRole
from fhir.resources.R4B.location import Location as _R4BLocation
from fhir.resources.R4B.healthcareservice import HealthcareService as _R4BHealthcareService
from fhir.resources.R4B.organization import Organization as _R4BOrganization
from fhir.resources.R4B.insuranceplan import InsurancePlan as _R4BInsurancePlan
from fhir.resources.R4B.group import Group as _R4BGroup
from fhir.resources.R4B.basic import Basic as _R4BBasic
from fhir.resources.R4B.medicationknowledge import MedicationKnowledge as _R4BMedicationKnowledge
from fhir.resources.R4B.careplan import CarePlan as _R4BCarePlan
from fhir.resources.R4B.servicerequest import ServiceRequest as _R4BServiceRequest
from fhir.resources.R4B.immunization import Immunization as _R4BImmunization
from pydantic import ValidationError as _PydanticValidationError

_R4B_MODELS_BY_RESOURCE_TYPE = {
    "Bundle": _R4BBundle,
    "Observation": _R4BObservation,
    "Patient": _R4BPatient,
    "Encounter": _R4BEncounter,
    "MedicationRequest": _R4BMedicationRequest,
    "AllergyIntolerance": _R4BAllergyIntolerance,
    "Condition": _R4BCondition,
    "Procedure": _R4BProcedure,
    "Coverage": _R4BCoverage,
    "Claim": _R4BClaim,
    "ClaimResponse": _R4BClaimResponse,
    "ExplanationOfBenefit": _R4BExplanationOfBenefit,
    "DocumentReference": _R4BDocumentReference,
    "PractitionerRole": _R4BPractitionerRole,
    "Location": _R4BLocation,
    "HealthcareService": _R4BHealthcareService,
    "Organization": _R4BOrganization,
    "InsurancePlan": _R4BInsurancePlan,
    "Group": _R4BGroup,
    "Basic": _R4BBasic,
    "MedicationKnowledge": _R4BMedicationKnowledge,
    "CarePlan": _R4BCarePlan,
    "Immunization": _R4BImmunization,
    "ServiceRequest": _R4BServiceRequest,
}


def validate_fhir_structure(obj: dict) -> list[str]:
    """Best-effort FHIR R4B structural validation using `fhir.resources`.

    Returns a list of human-readable warning strings (empty if the resource
    validates, or if its resourceType isn't one we have a model for). This
    is intentionally non-blocking: reconciliation proceeds against the raw
    dict regardless, since real-world target systems sometimes emit
    near-conformant JSON and we'd rather surface a warning than hard-fail a
    comparison the caller still needs.
    """
    resource_type = obj.get("resourceType")
    model = _R4B_MODELS_BY_RESOURCE_TYPE.get(resource_type)
    if model is None:
        return []
    try:
        model(**obj)
    except _PydanticValidationError as exc:
        warnings = []
        for error in exc.errors():
            loc = ".".join(str(p) for p in error.get("loc", ()))
            warnings.append(f"{loc}: {error.get('msg')}" if loc else str(error.get("msg")))
        return warnings
    return []


def parse_fhir_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle (or single Observation) JSON
    object into patient + encounter + observations. Used by both the CLI
    (after reading a file) and the API (after decoding a request body).
    """
    if obj.get("resourceType") == "Observation":
        return {"patient": None, "encounter": None, "observations": [obj]}
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Target must be an Observation or a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    encounters = [r for r in entries if r.get("resourceType") == "Encounter"]
    if len(encounters) > 1:
        raise ValueError(f"Prototype supports exactly one Encounter resource; found {len(encounters)}")
    observations = [r for r in entries if r.get("resourceType") == "Observation"]
    if not observations:
        raise ValueError("Bundle contains no Observation resources")
    patient = patients[0] if patients else None
    encounter = encounters[0] if encounters else None
    return {"patient": patient, "encounter": encounter, "observations": observations}


def parse_fhir_bundle_multi(obj: dict) -> list:
    """Parse a FHIR Bundle that may contain multiple Patient resources (a
    real batch export), grouping each Patient with the Encounter(s) and
    Observation(s) that reference it.

    Unlike `parse_fhir_bundle` (which rejects a Bundle with more than one
    Patient), this returns one group per Patient resource found:
    [{"patient": dict, "encounter": dict | None, "observations": [dict, ...]}, ...].

    Observations/Encounters that don't reference any Patient in the bundle
    are dropped from all groups (they can't be attributed); this mirrors
    the existing PATIENT.REFERENCE consistency checks, which already treat
    an unresolvable subject reference as a failure elsewhere.

    If a Patient has more than one Encounter resource referencing it, all
    of them are kept (as `all_encounters`) rather than silently dropping
    all but the first; `reconciliation.engine.compare_batch()` uses this
    to surface scenario-registry.csv SC-029 ("duplicate encounter") instead
    of hiding the duplicate.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if not patients:
        raise ValueError("Bundle contains no Patient resources")
    encounters = [r for r in entries if r.get("resourceType") == "Encounter"]
    observations = [r for r in entries if r.get("resourceType") == "Observation"]

    encounters_by_patient_id: dict = {}
    for enc in encounters:
        pid = enc.get("subject", {}).get("reference", "").split("/")[-1]
        encounters_by_patient_id.setdefault(pid, []).append(enc)

    groups = []
    for patient in patients:
        pid = patient.get("id", "")
        patient_obs = [o for o in observations if o.get("subject", {}).get("reference", "").split("/")[-1] == pid]
        patient_encounters = encounters_by_patient_id.get(pid, [])
        groups.append({
            "patient": patient,
            "encounter": patient_encounters[0] if patient_encounters else None,
            "all_encounters": patient_encounters,
            "observations": patient_obs,
        })
    return groups


def ndjson_to_bundle(text: str) -> dict:
    """Convert NDJSON (newline-delimited FHIR resources, one JSON object per
    line -- the format used by FHIR Bulk Data Export and many real EHR/LIS
    batch feeds) into an in-memory `Bundle` dict, so the rest of Konkord
    (which is written against `Bundle.entry[].resource`) never needs to know
    the source file was NDJSON rather than a single Bundle JSON document.

    Blank lines are skipped. Each non-blank line must be a standalone JSON
    object (typically a FHIR resource); a line that fails to parse raises a
    `ValueError` naming the offending line number.
    """
    entries = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            resource = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid NDJSON on line {line_number}: {exc}") from exc
        entries.append({"resource": resource})
    if not entries:
        raise ValueError("NDJSON file contains no resources")
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def load_fhir_json(path: str) -> dict:
    """Load a FHIR JSON document from `path`, transparently handling both a
    single JSON document (`.json`, containing a Bundle or Observation) and
    NDJSON (`.ndjson`/`.ndjsonl`, one resource per line), returning a
    `Bundle`-shaped dict either way. This is the shared entry point used by
    every `load_fhir_*_bundle()` helper below, so NDJSON input works
    uniformly across all reconciliation domains, not just lab results.
    """
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() in (".ndjson", ".ndjsonl"):
        return ndjson_to_bundle(text)
    return json.loads(text)


def load_fhir_bundle(path: str) -> dict:
    """Load a FHIR Bundle (or single Observation) into patient + observations.

    Accepts a single-document `.json` file (Bundle or Observation) or an
    `.ndjson`/`.ndjsonl` file (one FHIR resource per line, as produced by
    FHIR Bulk Data Export or similar batch feeds).
    """
    obj = load_fhir_json(path)
    return parse_fhir_bundle(obj)


def load_observation(path: str) -> dict:
    """Backward-compatible single-observation load (pre-0.2 API)."""
    bundle = load_fhir_bundle(path)
    if len(bundle["observations"]) != 1:
        raise ValueError(f"Prototype requires exactly one FHIR Observation; found {len(bundle['observations'])}")
    return bundle["observations"][0]


def parse_fhir_medication_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    MedicationRequest resources, for medication order reconciliation.

    Any `MedicationAdministration` resources present are also captured (as
    `medication_administrations`) so that `reconciliation.engine.compare_many_medications()`
    can detect scenario-registry.csv SC-040 ("request confused with
    administration"): a source order whose code only matches a
    MedicationAdministration, not a MedicationRequest, in the target.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Medication target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    medication_requests = [r for r in entries if r.get("resourceType") == "MedicationRequest"]
    medication_administrations = [r for r in entries if r.get("resourceType") == "MedicationAdministration"]
    if not medication_requests and not medication_administrations:
        raise ValueError("Bundle contains no MedicationRequest resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "medication_requests": medication_requests,
            "medication_administrations": medication_administrations}


def load_fhir_medication_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + MedicationRequest resources."""
    obj = load_fhir_json(path)
    return parse_fhir_medication_bundle(obj)


def parse_fhir_allergy_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    AllergyIntolerance resources, for allergy reconciliation.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Allergy target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    allergy_intolerances = [r for r in entries if r.get("resourceType") == "AllergyIntolerance"]
    if not allergy_intolerances:
        raise ValueError("Bundle contains no AllergyIntolerance resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "allergy_intolerances": allergy_intolerances}


def load_fhir_allergy_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + AllergyIntolerance resources."""
    obj = load_fhir_json(path)
    return parse_fhir_allergy_bundle(obj)


def parse_fhir_immunization_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    Immunization resources, for vaccination-record reconciliation (CDC/HL7
    VXU^V04 source vs. US Core Immunization target).
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Immunization target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    immunizations = [r for r in entries if r.get("resourceType") == "Immunization"]
    if not immunizations:
        raise ValueError("Bundle contains no Immunization resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "immunizations": immunizations}


def load_fhir_immunization_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + Immunization resources."""
    obj = load_fhir_json(path)
    return parse_fhir_immunization_bundle(obj)


def parse_fhir_condition_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    Condition resources, for diagnosis reconciliation.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Condition target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    conditions = [r for r in entries if r.get("resourceType") == "Condition"]
    if not conditions:
        raise ValueError("Bundle contains no Condition resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "conditions": conditions}


def load_fhir_condition_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + Condition resources."""
    obj = load_fhir_json(path)
    return parse_fhir_condition_bundle(obj)


def parse_fhir_procedure_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    Procedure resources, for procedure reconciliation.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Procedure target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    procedures = [r for r in entries if r.get("resourceType") == "Procedure"]
    if not procedures:
        raise ValueError("Bundle contains no Procedure resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "procedures": procedures}


def load_fhir_procedure_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + Procedure resources."""
    obj = load_fhir_json(path)
    return parse_fhir_procedure_bundle(obj)


def parse_fhir_coverage_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    Coverage resources, for insurance coverage reconciliation.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Coverage target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    coverages = [r for r in entries if r.get("resourceType") == "Coverage"]
    if not coverages:
        raise ValueError("Bundle contains no Coverage resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "coverages": coverages}


def load_fhir_coverage_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + Coverage resources."""
    obj = load_fhir_json(path)
    return parse_fhir_coverage_bundle(obj)


def parse_fhir_claim_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    Claim resources (the prior-authorization request), for Prior
    Authorization reconciliation. This is Konkord's only FHIR-to-FHIR
    domain: there is no HL7v2 analog for a prior-auth request (the
    real-world wire format is X12 278, which Konkord does not parse), so
    the "source" system of record is itself modeled as FHIR Claim.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Claim source must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    claims = [r for r in entries if r.get("resourceType") == "Claim"]
    if not claims:
        raise ValueError("Bundle contains no Claim resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "claims": claims}


def load_fhir_claim_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + Claim resources."""
    obj = load_fhir_json(path)
    return parse_fhir_claim_bundle(obj)


def parse_fhir_claimresponse_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    ClaimResponse resources (the payer's prior-authorization decision).
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("ClaimResponse target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    claim_responses = [r for r in entries if r.get("resourceType") == "ClaimResponse"]
    if not claim_responses:
        raise ValueError("Bundle contains no ClaimResponse resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "claim_responses": claim_responses}


def load_fhir_claimresponse_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + ClaimResponse resources."""
    obj = load_fhir_json(path)
    return parse_fhir_claimresponse_bundle(obj)


def parse_fhir_eob_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    ExplanationOfBenefit resources (the payer's adjudicated claim), for
    Claims reconciliation. The "source" side of this domain is the
    submitted FHIR Claim (use="claim"), loaded via
    `parse_fhir_claim_bundle()` / `load_fhir_claim_bundle()`.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("ExplanationOfBenefit target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    eobs = [r for r in entries if r.get("resourceType") == "ExplanationOfBenefit"]
    if not eobs:
        raise ValueError("Bundle contains no ExplanationOfBenefit resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "eobs": eobs}


def load_fhir_eob_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + ExplanationOfBenefit resources."""
    obj = load_fhir_json(path)
    return parse_fhir_eob_bundle(obj)


def parse_fhir_document_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    DocumentReference resources, for document reconciliation.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Document target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    documents = [r for r in entries if r.get("resourceType") == "DocumentReference"]
    if not documents:
        raise ValueError("Bundle contains no DocumentReference resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "documents": documents}


def load_fhir_document_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + DocumentReference resources."""
    obj = load_fhir_json(path)
    return parse_fhir_document_bundle(obj)


def parse_fhir_resource_batch(obj: dict) -> list:
    """Parse an already-decoded FHIR Bundle JSON object into a flat list of
    its resources, regardless of resourceType.

    Used for Migration & Drift reconciliation (scenario-registry.csv
    SC-111..120), which compares a batch extract from a source system
    against the corresponding batch extract from a target system after
    migration -- unlike the other domains, it is not scoped to one
    resource type, since drift/count/lineage checks are cross-cutting
    across whatever resources the batch contains.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Migration batch must be a Bundle")
    resources = [e.get("resource", {}) for e in obj.get("entry", [])]
    if not resources:
        raise ValueError("Bundle contains no resources")
    return resources


def load_fhir_resource_batch(path: str) -> list:
    """Load a FHIR Bundle into a flat list of its resources."""
    obj = load_fhir_json(path)
    return parse_fhir_resource_batch(obj)


def _ref_id(reference_obj: dict) -> str:
    ref = (reference_obj or {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def parse_fhir_provider_directory_bundle(obj: dict) -> dict:
    """Parse a Da Vinci PDex Plan-Net style FHIR Bundle into a list of
    provider-directory entries, for Provider Directory reconciliation
    (scenario-registry.csv SC-121..130).

    Unlike the HL7v2-vs-FHIR domains, this is FHIR-to-FHIR, like Prior
    Authorization and Claims: both the "source" (credentialing system of
    record) and "target" (published directory) sides are themselves
    Plan-Net Bundles, since there is no HL7v2 analog for a provider
    directory.

    Each entry groups one PractitionerRole with its referenced
    Practitioner, Location(s), and HealthcareService(s):
    {"role": dict, "practitioner": dict | None, "locations": [dict, ...],
     "healthcare_services": [dict, ...]}.

    The Bundle-level `organizations` (keyed by id) and `insurance_plans`
    (list) are also returned, since SC-128 (health plan/network reference
    broken) is a batch-level consistency check between InsurancePlan.network
    references and the Organizations actually present in the bundle, not a
    per-entry field comparison.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Provider directory bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    practitioners = {r["id"]: r for r in entries if r.get("resourceType") == "Practitioner" and r.get("id")}
    organizations = {r["id"]: r for r in entries if r.get("resourceType") == "Organization" and r.get("id")}
    locations = {r["id"]: r for r in entries if r.get("resourceType") == "Location" and r.get("id")}
    healthcare_services = {r["id"]: r for r in entries if r.get("resourceType") == "HealthcareService" and r.get("id")}
    insurance_plans = [r for r in entries if r.get("resourceType") == "InsurancePlan"]
    practitioner_roles = [r for r in entries if r.get("resourceType") == "PractitionerRole"]
    if not practitioner_roles:
        raise ValueError("Bundle contains no PractitionerRole resources")

    directory_entries = []
    for role in practitioner_roles:
        practitioner = practitioners.get(_ref_id(role.get("practitioner")))
        role_locations = [locations[rid] for loc in role.get("location", [])
                           if (rid := _ref_id(loc)) in locations]
        role_services = [healthcare_services[rid] for hs in role.get("healthcareService", [])
                          if (rid := _ref_id(hs)) in healthcare_services]
        directory_entries.append({
            "role": role,
            "practitioner": practitioner,
            "locations": role_locations,
            "healthcare_services": role_services,
        })

    return {"entries": directory_entries, "organizations": organizations, "insurance_plans": insurance_plans}


def load_fhir_provider_directory_bundle(path: str) -> dict:
    """Load a FHIR Bundle into provider-directory entries."""
    obj = load_fhir_json(path)
    return parse_fhir_provider_directory_bundle(obj)


def parse_fhir_attribution_bundle(obj: dict) -> dict:
    """Parse a Da Vinci ATR (member attribution) style FHIR Bundle, for
    ATR/Member Attribution reconciliation (scenario-registry.csv
    SC-131..140).

    Like Provider Directory, this is FHIR-to-FHIR: the "source" side is
    the payer/ACO's bulk-exported attribution list ($davinci-data-export),
    and the "target" side is the provider's own panel as returned by the
    ATR "Member Attribution List Reconciliation API" -- there is no HL7v2
    analog for either.

    Returns {"groups": [Group dict, ...], "patients": {id: dict},
    "coverages": [Coverage dict, ...], "encounters": [Encounter dict, ...]}.
    A bundle may contain more than one Group (e.g. the provider side may
    expose one roster per provider), which is what makes SC-132 (member
    attributed to two providers) detectable: the same patient appearing as
    a member of two Groups with different `managingEntity` references.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Attribution bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    groups = [r for r in entries if r.get("resourceType") == "Group"]
    if not groups:
        raise ValueError("Bundle contains no Group resources")
    patients = {r["id"]: r for r in entries if r.get("resourceType") == "Patient" and r.get("id")}
    coverages = [r for r in entries if r.get("resourceType") == "Coverage"]
    encounters = [r for r in entries if r.get("resourceType") == "Encounter"]
    return {"groups": groups, "patients": patients, "coverages": coverages, "encounters": encounters}


def load_fhir_attribution_bundle(path: str) -> dict:
    """Load a FHIR Bundle into ATR/member-attribution resources."""
    obj = load_fhir_json(path)
    return parse_fhir_attribution_bundle(obj)


def _ext_value(resource: dict, url: str):
    """Return the value[x] payload of the first extension with the given
    `url` on `resource`, or None if absent. The Da Vinci PDex US Drug
    Formulary IG carries all formulary-specific data (drug tier, cost
    share, prior-authorization, etc.) as extensions on a `Basic` resource,
    since FHIR R4B has no native Formulary/FormularyItem resource type.
    """
    for ext in resource.get("extension", []):
        if ext.get("url") == url:
            for key, value in ext.items():
                if key.startswith("value"):
                    return value
    return None


def parse_fhir_formulary_bundle(obj: dict) -> dict:
    """Parse a Da Vinci PDex US Drug Formulary style FHIR Bundle, for
    Formulary reconciliation (scenario-registry.csv SC-141..150).

    FHIR-to-FHIR, like Provider Directory and ATR: there is no HL7v2
    analog for a drug formulary. Both "Formulary" and "FormularyItem" are
    represented as `Basic` resources (per the IG, since R4B has no native
    resource type for either), distinguished by `Basic.code.coding[0].code`
    ("Formulary" / "FormularyItem"), with all formulary-specific fields
    (drug tier, cost share, prior-authorization, step-therapy, quantity
    limit, pharmacy type, formulary/medication linkage, effective period)
    carried as `Basic.extension` entries.

    Returns {"items": [Basic dict, ...], "formularies": {id: dict},
    "medications": {id: dict}, "insurance_plans": {id: dict}}.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Formulary bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]

    def _basic_code(resource: dict) -> str:
        codings = resource.get("code", {}).get("coding", [])
        return codings[0].get("code", "") if codings else ""

    basics = [r for r in entries if r.get("resourceType") == "Basic"]
    items = [r for r in basics if _basic_code(r) == "FormularyItem"]
    formularies = {r["id"]: r for r in basics if _basic_code(r) == "Formulary" and r.get("id")}
    if not items:
        raise ValueError("Bundle contains no FormularyItem Basic resources")
    medications = {r["id"]: r for r in entries if r.get("resourceType") == "MedicationKnowledge" and r.get("id")}
    insurance_plans = {r["id"]: r for r in entries if r.get("resourceType") == "InsurancePlan" and r.get("id")}
    return {"items": items, "formularies": formularies, "medications": medications, "insurance_plans": insurance_plans}


def load_fhir_formulary_bundle(path: str) -> dict:
    """Load a FHIR Bundle into Formulary/FormularyItem resources."""
    obj = load_fhir_json(path)
    return parse_fhir_formulary_bundle(obj)


def parse_fhir_careplan_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of CarePlan resources, for CarePlan
    reconciliation (scenario-registry.csv SC-058, "Care plan goal
    omitted").

    FHIR-to-FHIR: a CarePlan is itself the system-of-record artifact on
    both sides (e.g. the ordering/authoring system vs. the system of
    record it was migrated/synced into); there is no HL7v2 analog.

    Returns {"care_plans": [CarePlan dict, ...]}, matched by resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("CarePlan bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    care_plans = [r for r in entries if r.get("resourceType") == "CarePlan"]
    if not care_plans:
        raise ValueError("Bundle contains no CarePlan resources")
    return {"care_plans": care_plans}


def load_fhir_careplan_bundle(path: str) -> dict:
    """Load a FHIR Bundle into CarePlan resources."""
    obj = load_fhir_json(path)
    return parse_fhir_careplan_bundle(obj)


def parse_fhir_servicerequest_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of ServiceRequest resources, for ServiceRequest
    reconciliation (scenario-registry.csv SC-059, "Service request intent
    changed").

    FHIR-to-FHIR: a ServiceRequest is itself the system-of-record artifact
    on both sides; there is no HL7v2 analog.

    Returns {"service_requests": [ServiceRequest dict, ...]}, matched by
    resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("ServiceRequest bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    service_requests = [r for r in entries if r.get("resourceType") == "ServiceRequest"]
    if not service_requests:
        raise ValueError("Bundle contains no ServiceRequest resources")
    return {"service_requests": service_requests}


def load_fhir_servicerequest_bundle(path: str) -> dict:
    """Load a FHIR Bundle into ServiceRequest resources."""
    obj = load_fhir_json(path)
    return parse_fhir_servicerequest_bundle(obj)


def parse_fhir_goal_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of Goal resources, for Goal reconciliation
    (US Core Goal profile; scenario-registry.csv SC-159/SC-160).

    FHIR-to-FHIR: a standalone Goal (distinct from the goal *references*
    already checked on CarePlan via `parse_fhir_careplan_bundle`) is
    itself the system-of-record artifact on both sides; there is no
    HL7v2 analog.

    Returns {"goals": [Goal dict, ...]}, matched by resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Goal bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    goals = [r for r in entries if r.get("resourceType") == "Goal"]
    if not goals:
        raise ValueError("Bundle contains no Goal resources")
    return {"goals": goals}


def load_fhir_goal_bundle(path: str) -> dict:
    """Load a FHIR Bundle into Goal resources."""
    obj = load_fhir_json(path)
    return parse_fhir_goal_bundle(obj)


def parse_fhir_careteam_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of CareTeam resources, for CareTeam
    reconciliation (US Core CareTeam profile; scenario-registry.csv
    SC-161/SC-162).

    FHIR-to-FHIR: a CareTeam is itself the system-of-record artifact on
    both sides; there is no HL7v2 analog.

    Returns {"care_teams": [CareTeam dict, ...]}, matched by resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("CareTeam bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    care_teams = [r for r in entries if r.get("resourceType") == "CareTeam"]
    if not care_teams:
        raise ValueError("Bundle contains no CareTeam resources")
    return {"care_teams": care_teams}


def load_fhir_careteam_bundle(path: str) -> dict:
    """Load a FHIR Bundle into CareTeam resources."""
    obj = load_fhir_json(path)
    return parse_fhir_careteam_bundle(obj)


def parse_fhir_detectedissue_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of DetectedIssue resources, for Risk
    Adjustment "Gaps in Care & Information" reconciliation (Da Vinci Risk
    Adjustment IG; scenario-registry.csv SC-163/SC-164).

    FHIR-to-FHIR: a DetectedIssue (coding gap/suspected condition) is
    itself the system-of-record artifact on both sides (e.g. the
    analytics engine that first detects a gap vs. the system it is
    synced into for provider review); there is no HL7v2 analog.

    Returns {"detected_issues": [DetectedIssue dict, ...]}, matched by
    resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("DetectedIssue bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    detected_issues = [r for r in entries if r.get("resourceType") == "DetectedIssue"]
    if not detected_issues:
        raise ValueError("Bundle contains no DetectedIssue resources")
    return {"detected_issues": detected_issues}


def load_fhir_detectedissue_bundle(path: str) -> dict:
    """Load a FHIR Bundle into DetectedIssue resources."""
    obj = load_fhir_json(path)
    return parse_fhir_detectedissue_bundle(obj)


def parse_fhir_task_bundle(obj: dict) -> dict:
    """Parse a FHIR Bundle of Task resources, for Da Vinci Clinical Data
    Exchange (CDex) Task reconciliation (scenario-registry.csv
    SC-165/SC-166).

    FHIR-to-FHIR: a CDex data-request Task is itself the system-of-record
    artifact on both sides (requester vs. responder/fulfillment-tracking
    systems); there is no HL7v2 analog.

    Returns {"tasks": [Task dict, ...]}, matched by resource id.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("Task bundle must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    tasks = [r for r in entries if r.get("resourceType") == "Task"]
    if not tasks:
        raise ValueError("Bundle contains no Task resources")
    return {"tasks": tasks}


def load_fhir_task_bundle(path: str) -> dict:
    """Load a FHIR Bundle into Task resources."""
    obj = load_fhir_json(path)
    return parse_fhir_task_bundle(obj)


def parse_fhir_diagnosticreport_bundle(obj: dict) -> dict:
    """Parse an already-decoded FHIR Bundle JSON object into patient +
    DiagnosticReport resources, for US Core Laboratory Result reconciliation
    (scenario-registry.csv SC-167..169) of the OBR header fields that
    `adapters.hl7v2.parse_hl7_oru`/`parse_hl7_oru_batch` currently only use
    for OBX specimen-type grouping, never diff themselves.
    """
    if obj.get("resourceType") != "Bundle":
        raise ValueError("DiagnosticReport target must be a Bundle")
    entries = [e.get("resource", {}) for e in obj.get("entry", [])]
    patients = [r for r in entries if r.get("resourceType") == "Patient"]
    if len(patients) > 1:
        raise ValueError(f"Prototype supports exactly one Patient resource; found {len(patients)}")
    diagnostic_reports = [r for r in entries if r.get("resourceType") == "DiagnosticReport"]
    if not diagnostic_reports:
        raise ValueError("Bundle contains no DiagnosticReport resources")
    patient = patients[0] if patients else None
    return {"patient": patient, "diagnostic_reports": diagnostic_reports}


def load_fhir_diagnosticreport_bundle(path: str) -> dict:
    """Load a FHIR Bundle into patient + DiagnosticReport resources."""
    obj = load_fhir_json(path)
    return parse_fhir_diagnosticreport_bundle(obj)
