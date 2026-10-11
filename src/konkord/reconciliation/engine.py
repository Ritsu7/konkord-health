"""Observation-level comparison and multi-observation reconciliation.

`compare()` runs every registered rule for the "observation" domain against
one source/target pair. `compare_many()` adds record correlation (matching
by LOINC code), missing/duplicate detection, timestamp preservation, and
patient-reference consistency across a full HL7 ORU message vs. FHIR Bundle.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from ..rules import rules_for_domain
from ..evidence import build_report
from ..adapters.fhir import _ext_value, _ref_id


def compare(source: dict, target: dict) -> dict:
    findings = []
    for rule in rules_for_domain("observation"):
        result = rule.check(source, target)
        findings.append({
            "rule_id": rule.rule_id,
            "status": result.status,
            "source_value": str(result.source_value),
            "target_value": str(result.target_value),
            "explanation": result.explanation,
        })
    return build_report(findings)


def _target_loinc_codes(target: dict) -> list:
    return [c.get("code", "") for c in target.get("code", {}).get("coding", []) if c.get("system") == "http://loinc.org"]


def _patient_id_of(obs: dict) -> str:
    ref = obs.get("subject", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _encounter_ref_of(obs: dict) -> str:
    return obs.get("encounter", {}).get("reference", "")


def compare_terminology(source: dict, target: dict) -> dict:
    """Reconcile terminology/coding metadata from a single HL7v2 OBX
    segment's CWE-encoded code field (OBX-3) against a single FHIR
    Observation.code CodeableConcept.

    source: output of adapters.hl7v2.parse_hl7_obx() (single observation).
    target: output of adapters.fhir.load_observation() (single Observation).

    Deliberately separate from compare()/compare_many() (the "observation"
    domain): adding terminology checks here cannot change the PASS/FAIL
    outcome of existing lab-result reconciliations.
    """
    findings = []
    for rule in rules_for_domain("terminology"):
        result = rule.check(source, target)
        findings.append({
            "rule_id": rule.rule_id,
            "status": result.status,
            "source_value": str(result.source_value),
            "target_value": str(result.target_value),
            "explanation": result.explanation,
        })
    return build_report(findings)


def compare_many(source: dict, target: dict) -> dict:
    """Reconcile a multi-observation HL7 ORU message against a FHIR Bundle.

    source: output of adapters.hl7v2.parse_hl7_oru().
    target: output of adapters.fhir.load_fhir_bundle().

    Matching is by LOINC code; the prototype does not yet support repeated
    identical test codes within a single message/bundle (such repeats are
    reported as OBS[code].DUPLICATE on the target side).
    """
    findings = []
    target_by_code = {}
    for obs in target["observations"]:
        for code in _target_loinc_codes(obs):
            target_by_code.setdefault(code, []).append(obs)

    for src_obs in source["observations"]:
        code = src_obs["code"]
        if src_obs["code_system"] != "LN":
            findings.append({"rule_id": f"OBS[{code}].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Unsupported source coding system; requires mapping contract"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"OBS[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source observation has no corresponding target observation"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"OBS[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} observations with this code; expected 1"})
            continue
        target_obs = matches[0]
        sub_report = compare(src_obs, target_obs)
        for f in sub_report["checks"]:
            f = dict(f)
            f["rule_id"] = f"OBS[{code}].{f['rule_id']}"
            findings.append(f)

        if src_obs.get("timestamp"):
            effective = target_obs.get("effectiveDateTime", "")
            match = bool(effective) and effective.replace("-", "").replace(":", "").startswith(src_obs["timestamp"][:8])
            findings.append({"rule_id": f"OBS[{code}].TIMESTAMP", "status": "PASS" if match else "FAIL",
                              "source_value": src_obs["timestamp"], "target_value": effective,
                              "explanation": "Observation timestamp preservation (date-level comparison)"})
        else:
            findings.append({"rule_id": f"OBS[{code}].TIMESTAMP", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source observation timestamp supplied"})

    bundle_patient = target.get("patient")
    patient_ids = {_patient_id_of(o) for o in target["observations"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "Observations reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", ""), "target_value": declared_id,
                          "explanation": "All observations reference the bundle's declared Patient resource"})

    for rule in rules_for_domain("patient"):
        result = rule.check(source.get("patient"), bundle_patient)
        findings.append({
            "rule_id": rule.rule_id,
            "status": result.status,
            "source_value": str(result.source_value),
            "target_value": str(result.target_value),
            "explanation": result.explanation,
        })

    bundle_encounter = target.get("encounter")
    encounter_refs = {_encounter_ref_of(o) for o in target["observations"]}
    if bundle_encounter is None:
        if any(encounter_refs):
            findings.append({"rule_id": "ENCOUNTER.REFERENCE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Observations reference an encounter, but target bundle has no Encounter resource"})
        else:
            findings.append({"rule_id": "ENCOUNTER.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No Encounter resource or encounter reference present in target"})
    elif len(encounter_refs) > 1 or "" in encounter_refs:
        findings.append({"rule_id": "ENCOUNTER.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "Observations reference inconsistent or missing encounters"})
    else:
        declared_ref = next(iter(encounter_refs))
        encounter_id = bundle_encounter.get("id", "")
        match = encounter_id != "" and declared_ref.endswith(encounter_id)
        findings.append({"rule_id": "ENCOUNTER.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("encounter", {}).get("visit_number", "") if source.get("encounter") else "",
                          "target_value": encounter_id,
                          "explanation": "All observations reference the bundle's declared Encounter resource"})

    for rule in rules_for_domain("encounter"):
        result = rule.check(source.get("encounter"), bundle_encounter)
        findings.append({
            "rule_id": rule.rule_id,
            "status": result.status,
            "source_value": str(result.source_value),
            "target_value": str(result.target_value),
            "explanation": result.explanation,
        })

    return build_report(findings)


def _mrn_values(patient: dict) -> list:
    if not patient:
        return []
    values = []
    for ident in patient.get("identifier", []):
        codes = [c.get("code") for c in ident.get("type", {}).get("coding", [])]
        if "MR" in codes:
            values.append(ident.get("value", ""))
    return values


def _source_patient_identity(patient: dict):
    if not patient:
        return None
    family = patient.get("family_name", "")
    raw = patient.get("birth_date", "")
    if not family or not raw or len(raw) < 8:
        return None
    return (family, f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}")


def _target_patient_identity(patient: dict):
    if not patient:
        return None
    names = patient.get("name", [])
    family = names[0].get("family", "") if names else ""
    dob = patient.get("birthDate", "")
    if not family or not dob:
        return None
    return (family, dob)


def _target_encounter_identifier(encounter: dict):
    if not encounter:
        return ""
    for ident in encounter.get("identifier", []):
        if ident.get("value"):
            return ident["value"]
    return ""


def compare_batch(source_groups: list, target_groups: list) -> dict:
    """Reconcile a batched multi-patient HL7 ORU message against a FHIR
    Bundle containing multiple Patients.

    source_groups: output of adapters.hl7v2.parse_hl7_oru_batch().
    target_groups: output of adapters.fhir.parse_fhir_bundle_multi().

    Patients are correlated by MRN (HL7 PID-3 vs FHIR Patient.identifier
    with type code "MR"); a source patient with no matching target patient
    is reported as PATIENT[mrn].MATCH = FAIL rather than silently skipped,
    so coverage gaps in a batch are never hidden.

    Two cross-record identity defects become detectable once a batch has
    more than one patient to correlate against (scenario-registry.csv
    SC-019, SC-014):

    - IDENTITY.COLLISION (SC-019, "Identifier collision"): two or more
      distinct target Patient resources carry the same MRN identifier
      value, so a source patient with that MRN cannot be matched
      unambiguously.
    - IDENTITY.MERGE (SC-014, "Patients unintentionally merged"): two or
      more distinct source MRNs both resolve to the *same* target Patient
      resource (i.e. that Patient carries identifiers for more than one
      real-world source patient).

    A third defect, ENCOUNTER.DUPLICATE (SC-029, "Duplicate encounter"), is
    also detectable per-patient: if a matched target Patient has more than
    one Encounter resource referencing it (adapters.fhir.parse_fhir_bundle_multi
    keeps all of them in "all_encounters" rather than silently dropping all
    but the first), that is reported as a FAIL.

    Two further cross-record identity defects require comparing demographic
    identity (family name + birth date) across the whole batch, not just the
    MRN-matched pair (SC-011, SC-015):

    - IDENTITY.WRONG_PATIENT_ASSIGNMENT (SC-011, "Wrong patient assignment"):
      a source patient is matched by MRN to a target Patient whose
      demographic identity does not match the source, but *does* match a
      different source patient's identity in this batch -- i.e. the wrong
      patient's demographics landed under this MRN.
    - IDENTITY.SPLIT (SC-015, "Patient split into identities"): a source
      patient's demographic identity (family name + birth date) is found on
      more than one distinct target Patient resource, indicating the same
      real-world patient was split into separate target identities.

    Both checks are literal-match only (exact family name + ISO birth date)
    and only fire when both source and target expose full name + birth date;
    otherwise they are silently skipped (no false positives from incomplete
    data).
    """
    findings = []
    target_by_mrn: dict = {}
    target_identity_index: dict = {}
    for group in target_groups:
        for mrn in _mrn_values(group["patient"]):
            target_by_mrn.setdefault(mrn, []).append(group)
        identity = _target_patient_identity(group["patient"])
        if identity:
            target_identity_index.setdefault(identity, set()).add(group["patient"].get("id", ""))

    source_identity_index: dict = {}
    source_visit_index: dict = {}
    for group in source_groups:
        src_patient = group.get("patient") or {}
        identity = _source_patient_identity(src_patient)
        if identity and src_patient.get("id"):
            source_identity_index.setdefault(identity, set()).add(src_patient["id"])
        visit_number = (group.get("encounter") or {}).get("visit_number", "")
        if visit_number and src_patient.get("id"):
            source_visit_index.setdefault(visit_number, set()).add(src_patient["id"])

    matched_target_patient_ids: dict = {}

    for src_group in source_groups:
        src_patient = src_group.get("patient") or {}
        mrn = src_patient.get("id", "")
        if not mrn:
            findings.append({"rule_id": "PATIENT[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source patient group has no MRN (PID-3)"})
            continue
        matches = target_by_mrn.get(mrn, [])
        if not matches:
            findings.append({"rule_id": f"PATIENT[{mrn}].MATCH", "status": "FAIL", "source_value": mrn,
                              "target_value": "", "explanation": "No target Patient found with this MRN"})
            continue
        if len(matches) > 1:
            target_ids = [g["patient"].get("id", "") for g in matches]
            findings.append({"rule_id": f"PATIENT[{mrn}].IDENTITY.COLLISION", "status": "FAIL", "source_value": mrn,
                              "target_value": target_ids,
                              "explanation": f"{len(matches)} distinct target Patients ({target_ids}) share MRN {mrn}; ambiguous match"})
            continue
        target_patient_id = matches[0]["patient"].get("id", "")
        matched_target_patient_ids.setdefault(target_patient_id, set()).add(mrn)
        sub_report = compare_many(src_group, {
            "patient": matches[0]["patient"],
            "encounter": matches[0]["encounter"],
            "observations": matches[0]["observations"],
        })
        for f in sub_report["checks"]:
            f = dict(f)
            f["rule_id"] = f"PATIENT[{mrn}].{f['rule_id']}"
            findings.append(f)

        src_identity = _source_patient_identity(src_patient)
        target_identity = _target_patient_identity(matches[0]["patient"])
        if src_identity and target_identity:
            if src_identity != target_identity:
                other_mrns = source_identity_index.get(target_identity, set()) - {mrn}
                if other_mrns:
                    findings.append({
                        "rule_id": f"PATIENT[{mrn}].IDENTITY.WRONG_PATIENT_ASSIGNMENT", "status": "FAIL",
                        "source_value": src_identity, "target_value": target_identity,
                        "explanation": f"Target Patient {target_patient_id} matched by MRN {mrn} has a different "
                                       f"demographic identity than the source; that identity instead matches "
                                       f"source patient(s) {sorted(other_mrns)}, suggesting the wrong patient's "
                                       "data was assigned to this MRN",
                    })
            else:
                other_owners = target_identity_index.get(src_identity, set()) - {target_patient_id}
                if other_owners:
                    findings.append({
                        "rule_id": f"PATIENT[{mrn}].IDENTITY.SPLIT", "status": "FAIL",
                        "source_value": src_identity, "target_value": sorted(other_owners),
                        "explanation": f"Source patient {mrn}'s demographic identity also appears on target "
                                       f"Patient(s) {sorted(other_owners)} in addition to the correctly matched "
                                       f"Patient {target_patient_id}; the patient appears to have been split into "
                                       "multiple target identities",
                    })

        src_visit_number = (src_group.get("encounter") or {}).get("visit_number", "")
        target_visit_number = _target_encounter_identifier(matches[0].get("encounter"))
        if src_visit_number and target_visit_number and src_visit_number != target_visit_number:
            other_mrns = source_visit_index.get(target_visit_number, set()) - {mrn}
            if other_mrns:
                findings.append({
                    "rule_id": f"PATIENT[{mrn}].ENCOUNTER.WRONG_PATIENT_ASSIGNMENT", "status": "FAIL",
                    "source_value": src_visit_number, "target_value": target_visit_number,
                    "explanation": f"The Encounter attached to target Patient {target_patient_id} (matched by MRN "
                                   f"{mrn}) carries visit number {target_visit_number}, which belongs to source "
                                   f"patient(s) {sorted(other_mrns)}, not this one; the encounter appears to be "
                                   "associated with the wrong patient",
                })

        all_encounters = matches[0].get("all_encounters", [])
        if len(all_encounters) > 1:
            encounter_ids = [e.get("id", "") for e in all_encounters]
            findings.append({"rule_id": f"PATIENT[{mrn}].ENCOUNTER.DUPLICATE", "status": "FAIL",
                              "source_value": "", "target_value": encounter_ids,
                              "explanation": f"Target Patient {target_patient_id} has {len(all_encounters)} "
                                             f"Encounter resources ({encounter_ids}) instead of one"})

    for target_patient_id, mrns in matched_target_patient_ids.items():
        if len(mrns) > 1:
            findings.append({"rule_id": f"PATIENT[{target_patient_id}].IDENTITY.MERGE", "status": "FAIL",
                              "source_value": sorted(mrns), "target_value": target_patient_id,
                              "explanation": f"Target Patient {target_patient_id} carries identifiers for "
                                             f"{len(mrns)} distinct source MRNs ({sorted(mrns)}); patients "
                                             "appear to have been unintentionally merged"})

    matched_mrns = {g.get("patient", {}).get("id", "") for g in source_groups if g.get("patient")}
    for mrn, groups in target_by_mrn.items():
        if mrn and mrn not in matched_mrns:
            findings.append({"rule_id": f"PATIENT[{mrn}].MATCH", "status": "WARN", "source_value": "",
                              "target_value": mrn, "explanation": "Target Patient has no corresponding source patient group in this batch"})

    return build_report(findings)


def _medication_patient_id_of(med_request: dict) -> str:
    ref = med_request.get("subject", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def compare_many_medications(source: dict, target: dict) -> dict:
    """Reconcile an HL7 RDE^O11 medication order message against a FHIR
    Bundle of MedicationRequest resources.

    source: output of adapters.hl7v2.parse_hl7_rde().
    target: output of adapters.fhir.parse_fhir_medication_bundle().

    Matching is by medication code; the prototype does not yet support
    repeated identical medication codes within a single message/bundle
    (such repeats are reported as MED[code].DUPLICATE on the target side).

    If a source order's code has no matching MedicationRequest but does
    match a MedicationAdministration in the target, that is reported as
    MED[code].REQUEST_CONFUSED_WITH_ADMINISTRATION (scenario-registry.csv
    SC-040) rather than a plain MISSING, since the clinical record exists
    but under the wrong resource type (an order was conflated with a
    record of it actually being given).
    """
    findings = []
    target_by_code = {}
    for med_request in target["medication_requests"]:
        for code in _med_codes_of(med_request):
            target_by_code.setdefault(code, []).append(med_request)

    administration_by_code = {}
    for med_admin in target.get("medication_administrations", []):
        for code in _med_codes_of(med_admin):
            administration_by_code.setdefault(code, []).append(med_admin)

    for src_med in source["medications"]:
        code = src_med.get("code", "")
        if not code:
            findings.append({"rule_id": "MED[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source medication order has no give code"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            if administration_by_code.get(code):
                findings.append({"rule_id": f"MED[{code}].REQUEST_CONFUSED_WITH_ADMINISTRATION", "status": "FAIL",
                                  "source_value": "", "target_value": "",
                                  "explanation": "Source medication order's code matches a target "
                                                 "MedicationAdministration, not a MedicationRequest; the order "
                                                 "appears to have been conflated with a record of it being given"})
                continue
            findings.append({"rule_id": f"MED[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source medication order has no corresponding target MedicationRequest"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"MED[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} MedicationRequests with this code; expected 1"})
            continue
        target_med = matches[0]
        for rule in rules_for_domain("medication"):
            result = rule.check(src_med, target_med)
            findings.append({
                "rule_id": f"MED[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

    bundle_patient = target.get("patient")
    patient_ids = {_medication_patient_id_of(m) for m in target["medication_requests"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "MedicationRequests reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", "") if source.get("patient") else "",
                          "target_value": declared_id,
                          "explanation": "All MedicationRequests reference the bundle's declared Patient resource"})

    return build_report(findings)


def _med_codes_of(med_request: dict) -> list:
    return [c.get("code", "") for c in med_request.get("medicationCodeableConcept", {}).get("coding", [])]


def _allergy_patient_id_of(allergy: dict) -> str:
    ref = allergy.get("patient", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _allergy_codes_of(allergy: dict) -> list:
    return [c.get("code", "") for c in allergy.get("code", {}).get("coding", [])]


def _allergy_reaction_manifestations(target: dict) -> list:
    texts = []
    for r in target.get("reaction", []):
        for m in r.get("manifestation", []):
            if m.get("text"):
                texts.append(m["text"])
            for c in m.get("coding", []):
                if c.get("display"):
                    texts.append(c["display"])
    return texts


# Sentinel allergen codes conventionally used (by HL7v2 AL1-3 and/or FHIR
# AllergyIntolerance.code) to assert "no known allergies" rather than
# identify a real substance. SNOMED CT 716186003/160244002 are the standard
# "no known allergy" situation codes; "NKA"/"NO KNOWN ALLERGIES" are common
# site-defined HL7v2 AL1-3 text values for the same assertion.
_NO_KNOWN_ALLERGY_CODES = {"716186003", "160244002", "NKA", "NO KNOWN ALLERGIES", "N/A"}


def _is_no_known_allergy_code(code: str) -> bool:
    return code.strip().upper() in _NO_KNOWN_ALLERGY_CODES


def compare_many_allergies(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 message's AL1 (patient allergy) segments against a
    FHIR Bundle of AllergyIntolerance resources.

    source: output of adapters.hl7v2.parse_hl7_allergies().
    target: output of adapters.fhir.parse_fhir_allergy_bundle().

    Matching is by allergen code; the prototype does not yet support
    repeated identical allergen codes within a single message/bundle (such
    repeats are reported as ALLERGY[code].DUPLICATE on the target side).

    SC-047 (negative allergy assertion changed): a "no known allergies"
    assertion (sentinel codes in `_NO_KNOWN_ALLERGY_CODES`, e.g. SNOMED
    716186003/160244002 or site-defined "NKA") on one side must not be
    contradicted by one or more real allergen entries on the other side;
    such a contradiction is reported as `ALLERGY.NO_KNOWN_ALLERGY_ASSERTION`.
    """
    findings = []
    source_codes = [a.get("code", "") for a in source["allergies"]]
    target_codes = [c for a in target["allergy_intolerances"] for c in _allergy_codes_of(a)]
    source_asserts_nka = any(_is_no_known_allergy_code(c) for c in source_codes if c)
    target_asserts_nka = any(_is_no_known_allergy_code(c) for c in target_codes if c)
    target_has_real_allergy = any(c and not _is_no_known_allergy_code(c) for c in target_codes)
    source_has_real_allergy = any(c and not _is_no_known_allergy_code(c) for c in source_codes)
    if source_asserts_nka and target_has_real_allergy:
        findings.append({
            "rule_id": "ALLERGY.NO_KNOWN_ALLERGY_ASSERTION", "status": "FAIL",
            "source_value": "no known allergies", "target_value": target_codes,
            "explanation": "Source asserts the patient has no known allergies, but the target bundle contains "
                           f"real allergen entries ({target_codes}); the negative allergy assertion was lost",
        })
    elif target_asserts_nka and source_has_real_allergy:
        findings.append({
            "rule_id": "ALLERGY.NO_KNOWN_ALLERGY_ASSERTION", "status": "FAIL",
            "source_value": source_codes, "target_value": "no known allergies",
            "explanation": "Target asserts the patient has no known allergies, but the source message contains "
                           f"real allergen entries ({source_codes}); a negative allergy assertion was introduced "
                           "that contradicts the source",
        })

    target_by_code = {}
    for allergy in target["allergy_intolerances"]:
        for code in _allergy_codes_of(allergy):
            if _is_no_known_allergy_code(code):
                continue
            target_by_code.setdefault(code, []).append(allergy)

    for src_allergy in source["allergies"]:
        code = src_allergy.get("code", "")
        if not code:
            findings.append({"rule_id": "ALLERGY[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source allergy has no allergen code"})
            continue
        if _is_no_known_allergy_code(code):
            # Not a real allergen; handled above by ALLERGY.NO_KNOWN_ALLERGY_ASSERTION.
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"ALLERGY[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source allergy has no corresponding target AllergyIntolerance"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"ALLERGY[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} AllergyIntolerances with this code; expected 1"})
            continue
        target_allergy = matches[0]
        for rule in rules_for_domain("allergy"):
            result = rule.check(src_allergy, target_allergy)
            findings.append({
                "rule_id": f"ALLERGY[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

        source_reactions = src_allergy.get("reactions") or []
        if source_reactions:
            manifestations = _allergy_reaction_manifestations(target_allergy)
            if not all(r in manifestations for r in source_reactions):
                for other in target["allergy_intolerances"]:
                    if other is target_allergy:
                        continue
                    other_manifestations = _allergy_reaction_manifestations(other)
                    if all(r in other_manifestations for r in source_reactions):
                        other_codes = _allergy_codes_of(other)
                        findings.append({
                            "rule_id": f"ALLERGY[{code}].REACTION_LINKED_TO_WRONG_SUBSTANCE", "status": "FAIL",
                            "source_value": source_reactions, "target_value": other_codes,
                            "explanation": f"Source reaction(s) for allergen {code} are not found on its matched "
                                           f"target AllergyIntolerance, but are found on a different target "
                                           f"AllergyIntolerance (allergen code(s) {other_codes}); the reaction "
                                           "appears to be linked to the wrong substance",
                        })
                        break

    bundle_patient = target.get("patient")
    patient_ids = {_allergy_patient_id_of(a) for a in target["allergy_intolerances"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "AllergyIntolerances reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", "") if source.get("patient") else "",
                          "target_value": declared_id,
                          "explanation": "All AllergyIntolerances reference the bundle's declared Patient resource"})

    return build_report(findings)


def _immunization_codes_of(immunization: dict) -> list:
    return [c.get("code", "") for c in immunization.get("vaccineCode", {}).get("coding", [])]


def _immunization_patient_id_of(immunization: dict) -> str:
    ref = immunization.get("patient", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def compare_many_immunizations(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2.5.1 VXU^V04 message's RXA (administration)
    segments against a FHIR Bundle of Immunization resources.

    source: output of adapters.hl7v2.parse_hl7_immunizations().
    target: output of adapters.fhir.parse_fhir_immunization_bundle().

    Matching is by vaccine (CVX) code; the prototype does not yet support
    repeated identical vaccine codes within a single message/bundle (such
    repeats are reported as IMMUNIZATION[code].DUPLICATE on the target
    side).

    SC-158 (immunization record dropped entirely): a source RXA with no
    matching target Immunization is reported as IMMUNIZATION[code].MISSING.
    """
    findings = []
    target_by_code = {}
    for immunization in target["immunizations"]:
        for code in _immunization_codes_of(immunization):
            target_by_code.setdefault(code, []).append(immunization)

    for src_imm in source["immunizations"]:
        code = src_imm.get("code", "")
        if not code:
            findings.append({"rule_id": "IMMUNIZATION[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source RXA segment has no administered (CVX) code"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"IMMUNIZATION[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source immunization has no corresponding target Immunization"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"IMMUNIZATION[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} Immunizations with this code; expected 1"})
            continue
        target_imm = matches[0]
        for rule in rules_for_domain("immunization"):
            result = rule.check(src_imm, target_imm)
            findings.append({
                "rule_id": f"IMMUNIZATION[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

    bundle_patient = target.get("patient")
    patient_ids = {_immunization_patient_id_of(i) for i in target["immunizations"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "Immunizations reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", "") if source.get("patient") else "",
                          "target_value": declared_id,
                          "explanation": "All Immunizations reference the bundle's declared Patient resource"})

    return build_report(findings)


def _condition_codes_of(condition: dict) -> list:
    return [c.get("code", "") for c in condition.get("code", {}).get("coding", [])]


def _condition_patient_id_of(condition: dict) -> str:
    ref = condition.get("subject", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _condition_encounter_ref_of(condition: dict) -> str:
    return condition.get("encounter", {}).get("reference", "")


def compare_many_conditions(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 message's DG1 (diagnosis) segments against a FHIR
    Bundle of Condition resources.

    source: output of adapters.hl7v2.parse_hl7_conditions().
    target: output of adapters.fhir.parse_fhir_condition_bundle().

    Matching is by diagnosis code; the prototype does not yet support
    repeated identical diagnosis codes within a single message/bundle
    (such repeats are reported as CONDITION[code].DUPLICATE on the target
    side).

    SC-060 (diagnosis encounter relationship lost): if the source message
    carries an encounter (PV1 present), every matched target Condition must
    reference that same encounter; a Condition with no/mismatched
    encounter reference is reported as CONDITION[code].ENCOUNTER.REFERENCE.
    """
    findings = []
    target_by_code = {}
    for condition in target["conditions"]:
        for code in _condition_codes_of(condition):
            target_by_code.setdefault(code, []).append(condition)

    source_encounter_id = (source.get("encounter") or {}).get("visit_number", "")

    for src_condition in source["conditions"]:
        code = src_condition.get("code", "")
        if not code:
            findings.append({"rule_id": "CONDITION[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source diagnosis has no diagnosis code"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"CONDITION[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source diagnosis has no corresponding target Condition"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"CONDITION[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} Conditions with this code; expected 1"})
            continue
        target_condition = matches[0]
        for rule in rules_for_domain("condition"):
            result = rule.check(src_condition, target_condition)
            findings.append({
                "rule_id": f"CONDITION[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })
        if source_encounter_id:
            target_encounter_ref = _condition_encounter_ref_of(target_condition)
            match = target_encounter_ref.endswith(f"/{source_encounter_id}") or target_encounter_ref == source_encounter_id
            findings.append({"rule_id": f"CONDITION[{code}].ENCOUNTER.REFERENCE",
                              "status": "PASS" if match else "FAIL",
                              "source_value": source_encounter_id, "target_value": target_encounter_ref,
                              "explanation": "Diagnosis-to-encounter relationship preservation (PV1-19 visit "
                                             "number vs Condition.encounter.reference)"})

    bundle_patient = target.get("patient")
    patient_ids = {_condition_patient_id_of(c) for c in target["conditions"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "Conditions reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", "") if source.get("patient") else "",
                          "target_value": declared_id,
                          "explanation": "All Conditions reference the bundle's declared Patient subject"})

    return build_report(findings)


def _procedure_codes_of(procedure: dict) -> list:
    return [c.get("code", "") for c in procedure.get("code", {}).get("coding", [])]


def _procedure_patient_id_of(procedure: dict) -> str:
    ref = procedure.get("subject", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def compare_many_procedures(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 message's PR1 (procedure) segments against a FHIR
    Bundle of Procedure resources.

    source: output of adapters.hl7v2.parse_hl7_procedures().
    target: output of adapters.fhir.parse_fhir_procedure_bundle().

    Matching is by procedure code; the prototype does not yet support
    repeated identical procedure codes within a single message/bundle
    (such repeats are reported as PROCEDURE[code].DUPLICATE on the target
    side).
    """
    findings = []
    target_by_code = {}
    for procedure in target["procedures"]:
        for code in _procedure_codes_of(procedure):
            target_by_code.setdefault(code, []).append(procedure)

    for src_procedure in source["procedures"]:
        code = src_procedure.get("code", "")
        if not code:
            findings.append({"rule_id": "PROCEDURE[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source procedure has no procedure code"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"PROCEDURE[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source procedure has no corresponding target Procedure"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"PROCEDURE[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} Procedures with this code; expected 1"})
            continue
        target_procedure = matches[0]
        for rule in rules_for_domain("procedure"):
            result = rule.check(src_procedure, target_procedure)
            findings.append({
                "rule_id": f"PROCEDURE[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

    bundle_patient = target.get("patient")
    patient_ids = {_procedure_patient_id_of(p) for p in target["procedures"]}
    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})
    elif len(patient_ids) > 1 or "" in patient_ids:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "FAIL", "source_value": "",
                          "target_value": "", "explanation": "Procedures reference inconsistent or missing patient subjects"})
    else:
        declared_id = bundle_patient.get("id", "")
        match = declared_id != "" and patient_ids == {declared_id}
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "PASS" if match else "FAIL",
                          "source_value": source.get("patient", {}).get("id", "") if source.get("patient") else "",
                          "target_value": declared_id,
                          "explanation": "All Procedures reference the bundle's declared Patient subject"})

    return build_report(findings)


def _coverage_beneficiary_id_of(coverage: dict) -> str:
    ref = coverage.get("beneficiary", {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def compare_many_coverages(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 message's IN1 (insurance) segments against a FHIR
    Bundle of Coverage resources.

    source: output of adapters.hl7v2.parse_hl7_coverage().
    target: output of adapters.fhir.parse_fhir_coverage_bundle().

    Matching is by member ID (IN1-49 vs Coverage.subscriberId); the
    prototype does not yet support repeated identical member IDs within a
    single message/bundle (such repeats are reported as
    COVERAGE[member_id].DUPLICATE on the target side -- SC-069).

    SC-065 (beneficiary changed): every matched target Coverage must
    reference the same patient as the bundle's declared Patient; a
    Coverage with no/mismatched beneficiary reference is reported as
    COVERAGE[member_id].BENEFICIARY.
    """
    findings = []
    target_by_member_id = {}
    for coverage in target["coverages"]:
        member_id = coverage.get("subscriberId", "")
        if member_id:
            target_by_member_id.setdefault(member_id, []).append(coverage)

    bundle_patient = target.get("patient")
    declared_patient_id = bundle_patient.get("id", "") if bundle_patient else ""

    for src_coverage in source["coverages"]:
        member_id = src_coverage.get("member_id", "")
        if not member_id:
            findings.append({"rule_id": "COVERAGE[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source coverage has no member ID (IN1-49)"})
            continue
        matches = target_by_member_id.get(member_id, [])
        if not matches:
            findings.append({"rule_id": f"COVERAGE[{member_id}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source coverage has no corresponding target Coverage"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"COVERAGE[{member_id}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} Coverages with this member ID; expected 1"})
            continue
        target_coverage = matches[0]
        for rule in rules_for_domain("coverage"):
            result = rule.check(src_coverage, target_coverage)
            findings.append({
                "rule_id": f"COVERAGE[{member_id}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })
        if declared_patient_id:
            beneficiary_id = _coverage_beneficiary_id_of(target_coverage)
            match = beneficiary_id == declared_patient_id
            findings.append({"rule_id": f"COVERAGE[{member_id}].BENEFICIARY",
                              "status": "PASS" if match else "FAIL",
                              "source_value": declared_patient_id, "target_value": beneficiary_id,
                              "explanation": "Coverage beneficiary preservation (Coverage.beneficiary.reference "
                                             "vs bundle's declared Patient)"})

    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})

    return build_report(findings)


def _identifier_of(resource: dict) -> str:
    identifiers = resource.get("identifier", [])
    return identifiers[0].get("value", "") if identifiers else ""


def _coverage_refs(resource: dict) -> list:
    return [ins.get("coverage", {}).get("reference", "") for ins in resource.get("insurance", [])
            if ins.get("coverage", {}).get("reference")]


def compare_many_prior_authorizations(source: dict, target: dict) -> dict:
    """Reconcile a FHIR Bundle of Claim (prior-authorization request)
    resources against a FHIR Bundle of ClaimResponse (payer decision)
    resources.

    source: output of adapters.fhir.parse_fhir_claim_bundle().
    target: output of adapters.fhir.parse_fhir_claimresponse_bundle().

    Matching is by identifier (Claim.identifier[0].value vs
    ClaimResponse.identifier[0].value); the prototype does not yet support
    repeated identical identifiers within a single bundle.

    SC-077 (requested vs approved service mismatch): every
    ClaimResponse.item.itemSequence must reference an existing Claim.item
    position (1-based), and every submitted Claim.item must have a
    corresponding adjudicated item -- reported as
    PRIORAUTH[id].SERVICE_MISMATCH.

    SC-079 (coverage link lost): the ClaimResponse's insurance[].coverage
    references must include every reference the Claim declared -- reported
    as PRIORAUTH[id].COVERAGE_LINK.

    SC-073 (service code altered): base FHIR R4B `ClaimResponse.item` has
    no native `productOrService` element, so the adjudicated service code
    is carried as a `productOrService` extension on the response item (the
    same pattern used for Formulary/ATR extension data elsewhere in this
    engine); each matched response item's extension value must agree with
    the submitted Claim item's `productOrService` -- reported per item as
    PRIORAUTH[id].ITEM[seq].SERVICE_CODE.

    SC-076 (supporting information omitted): base FHIR R4B `ClaimResponse`
    has no `supportingInfo` echo of the request's `supportingInfo`, so it
    is carried as a `supportingInfo` extension on the ClaimResponse; if the
    Claim declared supportingInfo, the matched ClaimResponse's extension
    must be present -- reported as PRIORAUTH[id].SUPPORTING_INFO.
    """
    findings = []
    target_by_id = {}
    for claim_response in target["claim_responses"]:
        identifier = _identifier_of(claim_response)
        if identifier:
            target_by_id.setdefault(identifier, []).append(claim_response)

    for claim in source["claims"]:
        identifier = _identifier_of(claim)
        if not identifier:
            findings.append({"rule_id": "PRIORAUTH[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source Claim has no identifier"})
            continue
        matches = target_by_id.get(identifier, [])
        if not matches:
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source Claim has no corresponding target ClaimResponse"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} ClaimResponses with this identifier; expected 1"})
            continue
        claim_response = matches[0]
        for rule in rules_for_domain("priorauth"):
            result = rule.check(claim, claim_response)
            findings.append({
                "rule_id": f"PRIORAUTH[{identifier}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

        claim_item_count = len(claim.get("item", []))
        response_sequences = {i.get("itemSequence") for i in claim_response.get("item", [])}
        valid_sequences = set(range(1, claim_item_count + 1))
        if not response_sequences:
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].SERVICE_MISMATCH", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "",
                              "explanation": "Target ClaimResponse has no adjudicated items"})
        else:
            match = response_sequences == valid_sequences
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].SERVICE_MISMATCH",
                              "status": "PASS" if match else "FAIL",
                              "source_value": sorted(valid_sequences), "target_value": sorted(response_sequences),
                              "explanation": "Every submitted Claim item has exactly one corresponding "
                                             "adjudicated ClaimResponse item, and vice versa"})

        source_coverage_refs = set(_coverage_refs(claim))
        if not source_coverage_refs:
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].COVERAGE_LINK", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "",
                              "explanation": "Source Claim declares no insurance coverage reference"})
        else:
            target_coverage_refs = set(_coverage_refs(claim_response))
            match = source_coverage_refs.issubset(target_coverage_refs)
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].COVERAGE_LINK",
                              "status": "PASS" if match else "FAIL",
                              "source_value": sorted(source_coverage_refs), "target_value": sorted(target_coverage_refs),
                              "explanation": "Coverage link preservation (Claim.insurance[].coverage.reference "
                                             "vs ClaimResponse.insurance[].coverage.reference)"})

        response_items_by_seq = {i.get("itemSequence"): i for i in claim_response.get("item", [])}
        for seq_position, claim_item in enumerate(claim.get("item", []), start=1):
            source_service = (claim_item.get("productOrService") or {}).get("coding", [])
            response_item = response_items_by_seq.get(seq_position)
            if response_item is None:
                continue
            target_service = _ext_value(response_item, "productOrService") or {}
            target_coding = target_service.get("coding", [])
            if not source_service:
                findings.append({"rule_id": f"PRIORAUTH[{identifier}].ITEM[{seq_position}].SERVICE_CODE",
                                  "status": "INDETERMINATE", "source_value": "", "target_value": "",
                                  "explanation": "Source Claim item has no productOrService"})
            else:
                match = source_service == target_coding
                findings.append({"rule_id": f"PRIORAUTH[{identifier}].ITEM[{seq_position}].SERVICE_CODE",
                                  "status": "PASS" if match else "FAIL",
                                  "source_value": source_service, "target_value": target_coding,
                                  "explanation": "Service code preservation (Claim.item.productOrService vs "
                                                 "ClaimResponse.item.extension[productOrService])"})

        source_supporting_info = claim.get("supportingInfo", [])
        if not source_supporting_info:
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].SUPPORTING_INFO", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "",
                              "explanation": "Source Claim declares no supportingInfo"})
        else:
            target_supporting_info = _ext_value(claim_response, "supportingInfo")
            findings.append({"rule_id": f"PRIORAUTH[{identifier}].SUPPORTING_INFO",
                              "status": "PASS" if target_supporting_info is not None else "FAIL",
                              "source_value": "present", "target_value": target_supporting_info or "",
                              "explanation": "Supporting information preservation (Claim.supportingInfo vs "
                                             "ClaimResponse.extension[supportingInfo])"})

    return build_report(findings)


def _claim_item_key(item: dict) -> tuple:
    coding = item.get("productOrService", {}).get("coding", [])
    code = coding[0].get("code", "") if coding else ""
    return (item.get("sequence"), code, item.get("servicedDate", ""), item.get("quantity", {}).get("value"))


def compare_many_claims(source: dict, target: dict) -> dict:
    """Reconcile a FHIR Bundle of Claim (use="claim", the submitted claim)
    resources against a FHIR Bundle of ExplanationOfBenefit (payer
    adjudication) resources.

    source: output of adapters.fhir.parse_fhir_claim_bundle().
    target: output of adapters.fhir.parse_fhir_eob_bundle().

    Matching is by identifier (Claim.identifier[0].value vs
    ExplanationOfBenefit.identifier[0].value); the prototype does not yet
    support repeated identical identifiers within a single bundle.

    SC-081/SC-085/SC-086/SC-087 (claim line omitted / service date changed
    / procedure code changed / service quantity changed): every
    Claim.item is matched to an ExplanationOfBenefit.item by sequence
    number; a missing sequence, or a servicedDate/productOrService/
    quantity mismatch on a matched pair, is reported as
    CLAIM[id].LINE_MISMATCH.

    SC-090 (claim/EOB link mismatched): ExplanationOfBenefit.claim.reference
    must point back to the matched Claim's id -- reported as
    CLAIM[id].EOB_LINK.
    """
    findings = []
    target_by_id = {}
    for eob in target["eobs"]:
        identifier = _identifier_of(eob)
        if identifier:
            target_by_id.setdefault(identifier, []).append(eob)

    for claim in source["claims"]:
        identifier = _identifier_of(claim)
        if not identifier:
            findings.append({"rule_id": "CLAIM[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source Claim has no identifier"})
            continue
        matches = target_by_id.get(identifier, [])
        if not matches:
            findings.append({"rule_id": f"CLAIM[{identifier}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source Claim has no corresponding target ExplanationOfBenefit"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"CLAIM[{identifier}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} ExplanationOfBenefits with this identifier; expected 1"})
            continue
        eob = matches[0]
        for rule in rules_for_domain("claim"):
            result = rule.check(claim, eob)
            findings.append({
                "rule_id": f"CLAIM[{identifier}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

        source_items = {i.get("sequence"): _claim_item_key(i) for i in claim.get("item", [])}
        target_items = {i.get("sequence"): _claim_item_key(i) for i in eob.get("item", [])}
        if not source_items:
            findings.append({"rule_id": f"CLAIM[{identifier}].LINE_MISMATCH", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "Source Claim has no items"})
        else:
            match = source_items == target_items
            findings.append({"rule_id": f"CLAIM[{identifier}].LINE_MISMATCH",
                              "status": "PASS" if match else "FAIL",
                              "source_value": source_items, "target_value": target_items,
                              "explanation": "Every submitted Claim.item (sequence, productOrService, "
                                             "servicedDate, quantity) must be preserved on the matching "
                                             "ExplanationOfBenefit.item"})

        claim_id = claim.get("id", "")
        eob_claim_ref = eob.get("claim", {}).get("reference", "")
        eob_claim_id = eob_claim_ref.split("/")[-1] if eob_claim_ref else ""
        if not claim_id:
            findings.append({"rule_id": f"CLAIM[{identifier}].EOB_LINK", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "Source Claim has no id"})
        else:
            match = claim_id == eob_claim_id
            findings.append({"rule_id": f"CLAIM[{identifier}].EOB_LINK",
                              "status": "PASS" if match else "FAIL",
                              "source_value": claim_id, "target_value": eob_claim_id,
                              "explanation": "Claim/EOB link preservation (ExplanationOfBenefit.claim.reference "
                                             "vs the matched Claim's id)"})

    return build_report(findings)


def compare_many_documents(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 message's TXA (transcription document header)
    segments against a FHIR Bundle of DocumentReference resources.

    source: output of adapters.hl7v2.parse_hl7_documents().
    target: output of adapters.fhir.parse_fhir_document_bundle().

    Matching is by document ID (TXA-12 vs DocumentReference.masterIdentifier
    .value); the prototype does not yet support repeated identical document
    IDs within a single message/bundle (such repeats are reported as
    DOCUMENT[id].DUPLICATE on the target side).

    SC-101 (attachment missing): every matched target DocumentReference
    must have a non-empty content[0].attachment (url or data) -- reported
    as DOCUMENT[id].ATTACHMENT.

    SC-107 (patient relationship changed): every matched target
    DocumentReference must reference the same patient as the bundle's
    declared Patient; reported as DOCUMENT[id].PATIENT_REF.
    """
    findings = []
    target_by_doc_id = {}
    for doc in target["documents"]:
        doc_id = doc.get("masterIdentifier", {}).get("value", "")
        if doc_id:
            target_by_doc_id.setdefault(doc_id, []).append(doc)

    bundle_patient = target.get("patient")
    declared_patient_id = bundle_patient.get("id", "") if bundle_patient else ""

    for src_doc in source["documents"]:
        doc_id = src_doc.get("document_id", "")
        if not doc_id:
            findings.append({"rule_id": "DOCUMENT[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source document has no unique document number (TXA-12)"})
            continue
        matches = target_by_doc_id.get(doc_id, [])
        if not matches:
            findings.append({"rule_id": f"DOCUMENT[{doc_id}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source document has no corresponding target DocumentReference"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"DOCUMENT[{doc_id}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} DocumentReferences with this document ID; expected 1"})
            continue
        target_doc = matches[0]
        for rule in rules_for_domain("document"):
            result = rule.check(src_doc, target_doc)
            findings.append({
                "rule_id": f"DOCUMENT[{doc_id}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

        content = target_doc.get("content", [])
        attachment = content[0].get("attachment", {}) if content else {}
        attachment_present = bool(attachment.get("url") or attachment.get("data"))
        findings.append({"rule_id": f"DOCUMENT[{doc_id}].ATTACHMENT",
                          "status": "PASS" if attachment_present else "FAIL",
                          "source_value": "present", "target_value": "present" if attachment_present else "absent",
                          "explanation": "DocumentReference.content[0].attachment must have a url or inline data"})

        if declared_patient_id:
            subject_ref = target_doc.get("subject", {}).get("reference", "")
            subject_id = subject_ref.split("/")[-1] if subject_ref else ""
            match = subject_id == declared_patient_id
            findings.append({"rule_id": f"DOCUMENT[{doc_id}].PATIENT_REF",
                              "status": "PASS" if match else "FAIL",
                              "source_value": declared_patient_id, "target_value": subject_id,
                              "explanation": "Document subject preservation (DocumentReference.subject.reference "
                                             "vs bundle's declared Patient)"})

    if bundle_patient is None:
        findings.append({"rule_id": "PATIENT.REFERENCE", "status": "INDETERMINATE", "source_value": "",
                          "target_value": "", "explanation": "No Patient resource present in target bundle"})

    return build_report(findings)


def _migration_key(resource: dict) -> str:
    """Identify a resource for migration matching: resourceType + id, or
    (if no id is present) resourceType + its first identifier.value.
    """
    resource_type = resource.get("resourceType", "")
    resource_id = resource.get("id", "")
    if resource_id:
        return f"{resource_type}/{resource_id}"
    identifiers = resource.get("identifier", [])
    if identifiers and identifiers[0].get("value"):
        return f"{resource_type}#{identifiers[0]['value']}"
    return ""


def compare_migration_batch(source: list, target: list) -> dict:
    """Reconcile a batch of arbitrary FHIR resources extracted from a
    source system (pre-migration) against the corresponding batch
    extracted from a target system (post-migration).

    source/target: output of adapters.fhir.parse_fhir_resource_batch().

    Unlike the per-resource-type domains above, migration assurance is a
    drift-detection problem over a whole batch rather than a single
    source/target pair: every source resource is matched to a target
    resource by resourceType + id (or, if absent, resourceType + first
    identifier.value), and cardinality/aggregate drift is reported across
    the batch.

    SC-111 (source record missing): RECORD[key].MISSING for any source
    resource absent from the target batch.

    SC-112 (unexpected duplicate): RECORD[key].DUPLICATE for any
    migration key matched by more than one target resource.

    SC-114 (transformation lineage missing): RECORD[key].LINEAGE -- every
    matched target resource must carry Resource.meta.source, the FHIR R4
    element that identifies the primary system a resource came from; used
    here as the migration lineage pointer back to the source system.

    SC-113 (category count discrepancy): CATEGORY[resourceType].COUNT
    compares per-resourceType counts between the source and target
    batches as a whole (not tied to any single matched pair).

    SC-118 (mapping behavior changed): RECORD[key].MAPPING_BEHAVIOR -- a
    concrete, detectable instance of the structural-mapping defect class.
    The source resource's `subject` reference must map straight across to
    the target resource's standard `Resource.subject` element; if it
    instead turns up inside the target resource's `extension[]` (or
    disappears, or points at a different patient), that is a mapping
    behavior change that a plain MISSING/DUPLICATE/LINEAGE check cannot
    see, since the resource itself still matches and may still carry
    lineage.

    SC-115 (provenance changed): RECORD[key].PROVENANCE -- for a matched
    pair of FHIR Provenance resources, the agent (who performed/requested
    the activity), activity (what was done), and entity (what source data
    it was derived from) must be preserved; a Provenance resource whose
    meta.source still matches but whose agent/activity/entity content was
    altered during migration is a lineage-content defect distinct from
    SC-114 (lineage presence).
    """
    findings = []
    target_by_key: dict = {}
    for resource in target:
        key = _migration_key(resource)
        if key:
            target_by_key.setdefault(key, []).append(resource)

    for resource in source:
        key = _migration_key(resource)
        if not key:
            findings.append({"rule_id": "RECORD[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source resource has no id or identifier to match on"})
            continue
        matches = target_by_key.get(key, [])
        if not matches:
            findings.append({"rule_id": f"RECORD[{key}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source resource has no corresponding target resource"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"RECORD[{key}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} resources with this key; expected 1"})
            continue
        target_resource = matches[0]
        meta_source = target_resource.get("meta", {}).get("source", "")
        findings.append({"rule_id": f"RECORD[{key}].LINEAGE",
                          "status": "PASS" if meta_source else "FAIL",
                          "source_value": "present" if meta_source else "",
                          "target_value": meta_source,
                          "explanation": "Target resource must carry meta.source identifying the migration's "
                                         "originating system"})

        # SC-118: mapping behavior changed -- the source's subject reference
        # was relocated during migration from the standard Resource.subject
        # element into an extension (or dropped) rather than mapped straight
        # across, which a plain MISSING/DUPLICATE/LINEAGE check can't see
        # because the resource itself still matches and still has lineage.
        source_subject = _ref_id(resource.get("subject", {}))
        if source_subject:
            target_subject = _ref_id(target_resource.get("subject", {}))
            if target_subject == source_subject:
                findings.append({"rule_id": f"RECORD[{key}].MAPPING_BEHAVIOR", "status": "PASS",
                                  "source_value": source_subject, "target_value": target_subject,
                                  "explanation": "Subject reference mapped to the standard Resource.subject element"})
            else:
                relocated = any(
                    _ref_id(ext.get("valueReference", {})) == source_subject
                    for ext in target_resource.get("extension", [])
                )
                if relocated:
                    findings.append({"rule_id": f"RECORD[{key}].MAPPING_BEHAVIOR", "status": "FAIL",
                                      "source_value": source_subject, "target_value": "",
                                      "explanation": "Subject reference's mapping behavior changed: relocated from "
                                                      "the standard Resource.subject element into an extension[] "
                                                      "instead of being mapped straight across"})
                elif not target_subject:
                    findings.append({"rule_id": f"RECORD[{key}].MAPPING_BEHAVIOR", "status": "FAIL",
                                      "source_value": source_subject, "target_value": "",
                                      "explanation": "Subject reference present in source but absent from the "
                                                      "target resource's standard element and any extension"})
                else:
                    findings.append({"rule_id": f"RECORD[{key}].MAPPING_BEHAVIOR", "status": "FAIL",
                                      "source_value": source_subject, "target_value": target_subject,
                                      "explanation": "Target Resource.subject references a different patient than "
                                                      "the source resource"})

        # SC-115: provenance changed -- a Provenance resource's agent,
        # activity, and entity content must survive migration unchanged,
        # even if meta.source lineage is still present (SC-114 only checks
        # that meta.source exists, not that the Provenance content itself
        # is intact).
        if resource.get("resourceType") == "Provenance":
            source_agents = sorted(_ref_id(a.get("who", {})) for a in resource.get("agent", []))
            target_agents = sorted(_ref_id(a.get("who", {})) for a in target_resource.get("agent", []))
            source_activity = ((resource.get("activity") or {}).get("coding") or [{}])[0].get("code", "")
            target_activity = ((target_resource.get("activity") or {}).get("coding") or [{}])[0].get("code", "")
            source_entities = sorted(_ref_id(e.get("what", {})) for e in resource.get("entity", []))
            target_entities = sorted(_ref_id(e.get("what", {})) for e in target_resource.get("entity", []))
            if (source_agents, source_activity, source_entities) == (target_agents, target_activity, target_entities):
                findings.append({"rule_id": f"RECORD[{key}].PROVENANCE", "status": "PASS",
                                  "source_value": {"agents": source_agents, "activity": source_activity,
                                                    "entities": source_entities},
                                  "target_value": {"agents": target_agents, "activity": target_activity,
                                                    "entities": target_entities},
                                  "explanation": "Provenance agent/activity/entity content preserved across migration"})
            else:
                findings.append({"rule_id": f"RECORD[{key}].PROVENANCE", "status": "FAIL",
                                  "source_value": {"agents": source_agents, "activity": source_activity,
                                                    "entities": source_entities},
                                  "target_value": {"agents": target_agents, "activity": target_activity,
                                                    "entities": target_entities},
                                  "explanation": "Provenance agent/activity/entity content changed between source "
                                                 "and target, even though the Provenance resource itself still "
                                                 "matches"})

    source_counts = Counter(r.get("resourceType", "") for r in source)
    target_counts = Counter(r.get("resourceType", "") for r in target)
    for resource_type in sorted(set(source_counts) | set(target_counts)):
        source_count = source_counts.get(resource_type, 0)
        target_count = target_counts.get(resource_type, 0)
        findings.append({"rule_id": f"CATEGORY[{resource_type}].COUNT",
                          "status": "PASS" if source_count == target_count else "FAIL",
                          "source_value": source_count, "target_value": target_count,
                          "explanation": f"Per-category resource count preservation for {resource_type or '(no resourceType)'}"})

    return build_report(findings)


def _parse_run_timestamp(value: str):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _pass_rate(report: dict) -> float | None:
    statuses = [c["status"] for c in report.get("checks", [])]
    if not statuses:
        return None
    return sum(1 for s in statuses if s == "PASS") / len(statuses)


def _indeterminate_rate_by_rule(report: dict) -> dict:
    by_rule: dict = {}
    for check in report.get("checks", []):
        rule_id = check["rule_id"]
        by_rule.setdefault(rule_id, []).append(check["status"])
    return {rule_id: statuses.count("INDETERMINATE") / len(statuses) for rule_id, statuses in by_rule.items()}


def compare_run_history(history: list, current: dict, max_sync_gap_hours: float = 24.0,
                         max_compliance_drop_pct: float = 10.0,
                         max_population_shift_pct: float = 20.0) -> dict:
    """Reconcile the current run's report against the run history for the
    same pipeline (prior reports from *any* `compare`/`compare_many_*()`
    function in this module, each with a run timestamp), to detect drift
    that only shows up across multiple runs over time and that a single
    snapshot comparison cannot carry.

    This function is domain-agnostic: it only reads the generic
    `{"checks": [{"rule_id", "status", ...}]}` shape produced by
    `evidence.report.build_report()`, which every `compare*()` function in
    this module returns. It was originally written for migration-batch
    history (SC-116/117/119/120) but applies unchanged to a run history of
    Claims, Coverage, Formulary, or any other domain's reports -- the
    "pipeline" is whatever the caller groups the history by (e.g. a
    `correlation_id`), not a migration-specific concept.

    history: ordered oldest-to-newest list of {"timestamp": ISO-8601 str,
        "report": report-dict-from-any-compare-function} for prior runs of
        this pipeline. May be empty (first-ever run).
    current: {"timestamp": ISO-8601 str, "report": report-dict} for the
        run being evaluated.

    SC-116 (incremental sync gap): RUN.SYNC_GAP -- the time between the
    most recent prior run and the current run must not exceed
    `max_sync_gap_hours`; a bigger gap means the incremental sync fell
    behind its expected schedule.

    SC-117 (late update overwritten): RECORD[key].LATE_UPDATE_OVERWRITTEN
    -- any per-record rule_id that PASSed in the most recent prior run but
    regresses to FAIL in the current run is reported as a likely
    overwrite/rollback of a previously-synced update, which a single
    snapshot comparison can't distinguish from "never synced".

    SC-119 (contract compliance degraded): RUN.CONTRACT_COMPLIANCE -- the
    current run's overall PASS rate must not drop more than
    `max_compliance_drop_pct` percentage points below the best PASS rate
    seen in the run history (a compliance-rate trend baseline).

    SC-120 (field population distribution changed): RULE[rule_id]
    .POPULATION_DISTRIBUTION -- for each per-rule INDETERMINATE rate
    (a proxy for "field not populated"), the current run's rate must not
    shift more than `max_population_shift_pct` percentage points from the
    historical average rate for that rule.
    """
    findings = []
    prior_runs = [h for h in history if _parse_run_timestamp(h.get("timestamp", ""))]
    current_ts = _parse_run_timestamp(current.get("timestamp", ""))
    current_report = current.get("report", {})

    if prior_runs and current_ts is not None:
        last_run = prior_runs[-1]
        last_ts = _parse_run_timestamp(last_run["timestamp"])
        if last_ts is not None:
            gap_hours = abs((current_ts - last_ts).total_seconds()) / 3600.0
            findings.append({"rule_id": "RUN.SYNC_GAP",
                              "status": "PASS" if gap_hours <= max_sync_gap_hours else "FAIL",
                              "source_value": f"<= {max_sync_gap_hours}h", "target_value": f"{gap_hours:.2f}h",
                              "explanation": "Gap since the last incremental sync run must not exceed the "
                                             "expected schedule"})
    else:
        findings.append({"rule_id": "RUN.SYNC_GAP", "status": "INDETERMINATE",
                          "explanation": "No prior run history available to establish a sync-gap baseline"})

    if prior_runs:
        last_statuses = {c["rule_id"]: c["status"] for c in prior_runs[-1].get("report", {}).get("checks", [])}
        current_statuses = {c["rule_id"]: c["status"] for c in current_report.get("checks", [])}
        for rule_id, prior_status in last_statuses.items():
            current_status = current_statuses.get(rule_id)
            if prior_status == "PASS" and current_status == "FAIL":
                findings.append({"rule_id": f"{rule_id}.LATE_UPDATE_OVERWRITTEN", "status": "FAIL",
                                  "source_value": "PASS", "target_value": "FAIL",
                                  "explanation": "This check passed in the most recent prior run but now fails: "
                                                 "an update appears to have been overwritten or rolled back"})
    else:
        findings.append({"rule_id": "RUN.LATE_UPDATE_OVERWRITTEN", "status": "INDETERMINATE",
                          "explanation": "No prior run history available to detect overwritten updates"})

    current_rate = _pass_rate(current_report)
    historical_rates = [r for r in (_pass_rate(h.get("report", {})) for h in prior_runs) if r is not None]
    if current_rate is None or not historical_rates:
        findings.append({"rule_id": "RUN.CONTRACT_COMPLIANCE", "status": "INDETERMINATE",
                          "explanation": "No prior run history available to establish a compliance-rate baseline"})
    else:
        best_rate = max(historical_rates)
        drop_pct = (best_rate - current_rate) * 100.0
        findings.append({"rule_id": "RUN.CONTRACT_COMPLIANCE",
                          "status": "PASS" if drop_pct <= max_compliance_drop_pct else "FAIL",
                          "source_value": f"{best_rate * 100:.1f}%", "target_value": f"{current_rate * 100:.1f}%",
                          "explanation": "Current run's PASS rate must not drop more than "
                                         f"{max_compliance_drop_pct} points below the best rate seen historically"})

    if not prior_runs:
        findings.append({"rule_id": "RUN.POPULATION_DISTRIBUTION", "status": "INDETERMINATE",
                          "explanation": "No prior run history available to establish a field-population baseline"})
    else:
        historical_indeterminate = [_indeterminate_rate_by_rule(h.get("report", {})) for h in prior_runs]
        current_indeterminate = _indeterminate_rate_by_rule(current_report)
        all_rule_ids = set(current_indeterminate) | set().union(*[set(h) for h in historical_indeterminate])
        for rule_id in sorted(all_rule_ids):
            historical_values = [h[rule_id] for h in historical_indeterminate if rule_id in h]
            if not historical_values:
                continue
            baseline = sum(historical_values) / len(historical_values)
            actual = current_indeterminate.get(rule_id, 0.0)
            shift_pct = abs(actual - baseline) * 100.0
            findings.append({"rule_id": f"RULE[{rule_id}].POPULATION_DISTRIBUTION",
                              "status": "PASS" if shift_pct <= max_population_shift_pct else "FAIL",
                              "source_value": f"{baseline * 100:.1f}%", "target_value": f"{actual * 100:.1f}%",
                              "explanation": "Per-rule field-population rate (non-INDETERMINATE share) must not "
                                             f"shift more than {max_population_shift_pct} points from the "
                                             "historical baseline"})

    return build_report(findings)


def compare_migration_run_history(history: list, current: dict, max_sync_gap_hours: float = 24.0,
                                   max_compliance_drop_pct: float = 10.0,
                                   max_population_shift_pct: float = 20.0) -> dict:
    """Deprecated alias for `compare_run_history()`, kept for backward
    compatibility. `compare_run_history` is domain-agnostic and not
    specific to migration pipelines; prefer calling it directly."""
    return compare_run_history(history, current, max_sync_gap_hours,
                                max_compliance_drop_pct, max_population_shift_pct)


def compare_many_careplans(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of CarePlan resources against a
    target FHIR Bundle of CarePlan resources (FHIR-to-FHIR; there is no
    HL7v2 analog for a care plan).

    Matching is by CarePlan.id.

    SC-058 (care plan goal omitted): CAREPLAN[id].GOAL -- every
    Goal reference present on the source CarePlan must still be present
    (by referenced id) on the matched target CarePlan; a goal dropped in
    transit/migration is reported as a FAIL.
    """
    findings = []
    target_by_id = {cp["id"]: cp for cp in target["care_plans"] if cp.get("id")}

    for source_plan in source["care_plans"]:
        plan_id = source_plan.get("id", "")
        if not plan_id:
            findings.append({"rule_id": "CAREPLAN[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source CarePlan has no id to match on"})
            continue
        target_plan = target_by_id.get(plan_id)
        if target_plan is None:
            findings.append({"rule_id": f"CAREPLAN[{plan_id}].MISSING", "status": "FAIL", "source_value": plan_id,
                              "target_value": "", "explanation": "Source CarePlan has no corresponding target CarePlan"})
            continue

        source_goal_ids = {_ref_id(g) for g in source_plan.get("goal", [])}
        target_goal_ids = {_ref_id(g) for g in target_plan.get("goal", [])}
        missing_goals = source_goal_ids - target_goal_ids
        findings.append({"rule_id": f"CAREPLAN[{plan_id}].GOAL",
                          "status": "PASS" if not missing_goals else "FAIL",
                          "source_value": sorted(source_goal_ids), "target_value": sorted(target_goal_ids),
                          "explanation": "All source CarePlan.goal references must be preserved on the target "
                                         "CarePlan" if not missing_goals else
                                         f"Target CarePlan is missing goal reference(s): {sorted(missing_goals)}"})

        source_status = source_plan.get("status", "")
        target_status = target_plan.get("status", "")
        findings.append({"rule_id": f"CAREPLAN[{plan_id}].STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "CarePlan.status preservation"})

    return build_report(findings)


def compare_many_servicerequests(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of ServiceRequest resources against a
    target FHIR Bundle of ServiceRequest resources (FHIR-to-FHIR; there is
    no HL7v2 analog for a service request).

    Matching is by ServiceRequest.id.

    SC-059 (service request intent changed): SERVICEREQUEST[id].INTENT --
    the target ServiceRequest.intent (e.g. "order", "plan", "proposal")
    must match the source's; a changed intent can silently alter
    downstream fulfillment behavior.
    """
    findings = []
    target_by_id = {sr["id"]: sr for sr in target["service_requests"] if sr.get("id")}

    for source_sr in source["service_requests"]:
        sr_id = source_sr.get("id", "")
        if not sr_id:
            findings.append({"rule_id": "SERVICEREQUEST[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source ServiceRequest has no id to match on"})
            continue
        target_sr = target_by_id.get(sr_id)
        if target_sr is None:
            findings.append({"rule_id": f"SERVICEREQUEST[{sr_id}].MISSING", "status": "FAIL", "source_value": sr_id,
                              "target_value": "", "explanation": "Source ServiceRequest has no corresponding target ServiceRequest"})
            continue

        source_intent = source_sr.get("intent", "")
        target_intent = target_sr.get("intent", "")
        findings.append({"rule_id": f"SERVICEREQUEST[{sr_id}].INTENT",
                          "status": "PASS" if source_intent == target_intent else "FAIL",
                          "source_value": source_intent, "target_value": target_intent,
                          "explanation": "ServiceRequest.intent preservation"})

        source_status = source_sr.get("status", "")
        target_status = target_sr.get("status", "")
        findings.append({"rule_id": f"SERVICEREQUEST[{sr_id}].STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "ServiceRequest.status preservation"})

    return build_report(findings)


def compare_many_goals(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of Goal resources against a target
    FHIR Bundle of Goal resources (FHIR-to-FHIR; there is no HL7v2 analog
    for a standalone Goal resource).

    Matching is by Goal.id.

    SC-159 (goal lifecycle status silently changed): GOAL[id].LIFECYCLE_STATUS.
    SC-160 (goal achievement status dropped): GOAL[id].ACHIEVEMENT_STATUS.
    """
    findings = []
    target_by_id = {g["id"]: g for g in target["goals"] if g.get("id")}

    for source_goal in source["goals"]:
        goal_id = source_goal.get("id", "")
        if not goal_id:
            findings.append({"rule_id": "GOAL[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source Goal has no id to match on"})
            continue
        target_goal = target_by_id.get(goal_id)
        if target_goal is None:
            findings.append({"rule_id": f"GOAL[{goal_id}].MISSING", "status": "FAIL", "source_value": goal_id,
                              "target_value": "", "explanation": "Source Goal has no corresponding target Goal"})
            continue

        source_status = source_goal.get("lifecycleStatus", "")
        target_status = target_goal.get("lifecycleStatus", "")
        findings.append({"rule_id": f"GOAL[{goal_id}].LIFECYCLE_STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "Goal.lifecycleStatus preservation"})

        source_achievement = (source_goal.get("achievementStatus", {}).get("coding") or [{}])[0].get("code", "")
        target_achievement = (target_goal.get("achievementStatus", {}).get("coding") or [{}])[0].get("code", "")
        if not source_achievement:
            findings.append({"rule_id": f"GOAL[{goal_id}].ACHIEVEMENT_STATUS", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "No source Goal.achievementStatus supplied"})
        else:
            findings.append({"rule_id": f"GOAL[{goal_id}].ACHIEVEMENT_STATUS",
                              "status": "PASS" if source_achievement == target_achievement else "FAIL",
                              "source_value": source_achievement, "target_value": target_achievement,
                              "explanation": "Goal.achievementStatus preservation"})

    return build_report(findings)


def compare_many_careteams(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of CareTeam resources against a
    target FHIR Bundle of CareTeam resources (FHIR-to-FHIR; there is no
    HL7v2 analog for a care team).

    Matching is by CareTeam.id.

    SC-161 (care team status silently changed): CARETEAM[id].STATUS.
    SC-162 (care team participant dropped): CARETEAM[id].PARTICIPANT.
    """
    findings = []
    target_by_id = {ct["id"]: ct for ct in target["care_teams"] if ct.get("id")}

    for source_ct in source["care_teams"]:
        ct_id = source_ct.get("id", "")
        if not ct_id:
            findings.append({"rule_id": "CARETEAM[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source CareTeam has no id to match on"})
            continue
        target_ct = target_by_id.get(ct_id)
        if target_ct is None:
            findings.append({"rule_id": f"CARETEAM[{ct_id}].MISSING", "status": "FAIL", "source_value": ct_id,
                              "target_value": "", "explanation": "Source CareTeam has no corresponding target CareTeam"})
            continue

        source_status = source_ct.get("status", "")
        target_status = target_ct.get("status", "")
        findings.append({"rule_id": f"CARETEAM[{ct_id}].STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "CareTeam.status preservation"})

        source_participant_ids = {_ref_id_of(p.get("member")) for p in source_ct.get("participant", [])}
        target_participant_ids = {_ref_id_of(p.get("member")) for p in target_ct.get("participant", [])}
        missing_participants = source_participant_ids - target_participant_ids
        findings.append({"rule_id": f"CARETEAM[{ct_id}].PARTICIPANT",
                          "status": "PASS" if not missing_participants else "FAIL",
                          "source_value": sorted(source_participant_ids), "target_value": sorted(target_participant_ids),
                          "explanation": "All source CareTeam.participant.member references must be preserved on the "
                                         "target CareTeam" if not missing_participants else
                                         f"Target CareTeam is missing participant reference(s): {sorted(missing_participants)}"})

    return build_report(findings)


def compare_many_detected_issues(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of DetectedIssue resources against a
    target FHIR Bundle of DetectedIssue resources (FHIR-to-FHIR; there is
    no HL7v2 analog), per the Da Vinci Risk Adjustment "Gaps in Care &
    Information" IG.

    Matching is by DetectedIssue.id.

    SC-163 (coding gap status silently changed, e.g. "preliminary" closed
    out as "final" without review): DETECTEDISSUE[id].STATUS.
    SC-164 (supporting evidence detail dropped in transit):
    DETECTEDISSUE[id].EVIDENCE_DETAIL.
    """
    findings = []
    target_by_id = {di["id"]: di for di in target["detected_issues"] if di.get("id")}

    for source_di in source["detected_issues"]:
        di_id = source_di.get("id", "")
        if not di_id:
            findings.append({"rule_id": "DETECTEDISSUE[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source DetectedIssue has no id to match on"})
            continue
        target_di = target_by_id.get(di_id)
        if target_di is None:
            findings.append({"rule_id": f"DETECTEDISSUE[{di_id}].MISSING", "status": "FAIL", "source_value": di_id,
                              "target_value": "", "explanation": "Source DetectedIssue has no corresponding target DetectedIssue"})
            continue

        source_status = source_di.get("status", "")
        target_status = target_di.get("status", "")
        findings.append({"rule_id": f"DETECTEDISSUE[{di_id}].STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "DetectedIssue.status preservation"})

        source_detail_ids = {_ref_id_of(d) for e in source_di.get("evidence", []) for d in e.get("detail", [])}
        target_detail_ids = {_ref_id_of(d) for e in target_di.get("evidence", []) for d in e.get("detail", [])}
        missing_detail = source_detail_ids - target_detail_ids
        findings.append({"rule_id": f"DETECTEDISSUE[{di_id}].EVIDENCE_DETAIL",
                          "status": "PASS" if not missing_detail else "FAIL",
                          "source_value": sorted(source_detail_ids), "target_value": sorted(target_detail_ids),
                          "explanation": "All source DetectedIssue.evidence.detail references must be preserved on "
                                         "the target DetectedIssue" if not missing_detail else
                                         f"Target DetectedIssue is missing evidence detail reference(s): {sorted(missing_detail)}"})

    return build_report(findings)


def compare_many_tasks(source: dict, target: dict) -> dict:
    """Reconcile a source FHIR Bundle of Task resources against a target
    FHIR Bundle of Task resources (FHIR-to-FHIR; there is no HL7v2
    analog), per the Da Vinci Clinical Data Exchange (CDex) IG's Task-based
    data-request workflow.

    Matching is by Task.id.

    SC-165 (task status silently regressed, e.g. "completed" reverted to
    "in-progress"): TASK[id].STATUS.
    SC-166 (task business status dropped, losing CDex-specific workflow
    state not covered by the base Task.status value set): TASK[id].BUSINESS_STATUS.
    """
    findings = []
    target_by_id = {t["id"]: t for t in target["tasks"] if t.get("id")}

    for source_task in source["tasks"]:
        task_id = source_task.get("id", "")
        if not task_id:
            findings.append({"rule_id": "TASK[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source Task has no id to match on"})
            continue
        target_task = target_by_id.get(task_id)
        if target_task is None:
            findings.append({"rule_id": f"TASK[{task_id}].MISSING", "status": "FAIL", "source_value": task_id,
                              "target_value": "", "explanation": "Source Task has no corresponding target Task"})
            continue

        source_status = source_task.get("status", "")
        target_status = target_task.get("status", "")
        findings.append({"rule_id": f"TASK[{task_id}].STATUS",
                          "status": "PASS" if source_status == target_status else "FAIL",
                          "source_value": source_status, "target_value": target_status,
                          "explanation": "Task.status preservation"})

        source_business = (source_task.get("businessStatus", {}).get("coding") or [{}])[0].get("code", "")
        target_business = (target_task.get("businessStatus", {}).get("coding") or [{}])[0].get("code", "")
        if not source_business:
            findings.append({"rule_id": f"TASK[{task_id}].BUSINESS_STATUS", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "No source Task.businessStatus supplied"})
        else:
            findings.append({"rule_id": f"TASK[{task_id}].BUSINESS_STATUS",
                              "status": "PASS" if source_business == target_business else "FAIL",
                              "source_value": source_business, "target_value": target_business,
                              "explanation": "Task.businessStatus preservation"})

    return build_report(findings)


def _diagnosticreport_codes_of(report: dict) -> list:
    return [c.get("code", "") for c in report.get("code", {}).get("coding", [])]


def compare_many_diagnosticreports(source: dict, target: dict) -> dict:
    """Reconcile an HL7v2 ORU^R01 message's OBR (observation request/report
    header) segments against a FHIR Bundle of DiagnosticReport resources,
    per the US Core Laboratory Result profile.

    source: output of adapters.hl7v2.parse_hl7_diagnosticreports().
    target: output of adapters.fhir.parse_fhir_diagnosticreport_bundle().

    Matching is by universal service (LOINC) code; the prototype does not
    yet support repeated identical report codes within a single
    message/bundle (such repeats are reported as
    DIAGNOSTICREPORT[code].DUPLICATE on the target side).

    SC-170 (diagnostic report dropped entirely): a source OBR with no
    matching target DiagnosticReport is reported as
    DIAGNOSTICREPORT[code].MISSING.
    """
    findings = []
    target_by_code = {}
    for report in target["diagnostic_reports"]:
        for code in _diagnosticreport_codes_of(report):
            target_by_code.setdefault(code, []).append(report)

    for src_report in source["diagnostic_reports"]:
        code = src_report.get("code", "")
        if not code:
            findings.append({"rule_id": "DIAGNOSTICREPORT[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source OBR segment has no universal service (LOINC) code"})
            continue
        matches = target_by_code.get(code, [])
        if not matches:
            findings.append({"rule_id": f"DIAGNOSTICREPORT[{code}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source diagnostic report has no corresponding target DiagnosticReport"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"DIAGNOSTICREPORT[{code}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} DiagnosticReports with this code; expected 1"})
            continue
        target_report = matches[0]
        for rule in rules_for_domain("diagnosticreport"):
            result = rule.check(src_report, target_report)
            findings.append({
                "rule_id": f"DIAGNOSTICREPORT[{code}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

    return build_report(findings)


def compare_export_run_history(history: list, current: dict, max_staleness_hours: float = 24.0) -> dict:
    """Reconcile the current Da Vinci ATR `$davinci-data-export` run
    against the export-run history for the same bulk-export pipeline, to
    detect a stale snapshot being used (SC-138) -- which needs longitudinal
    export-run timestamps that a single source/target snapshot pair
    cannot carry.

    history: ordered oldest-to-newest list of {"timestamp": ISO-8601 str}
        for prior `$davinci-data-export` runs of this pipeline.
    current: {"timestamp": ISO-8601 str} for the export snapshot actually
        being used for this reconciliation.

    SC-138 (stale bulk-export snapshot used): RUN.EXPORT_STALENESS -- the
    export snapshot being used must not be older than `max_staleness_hours`
    relative to the most recent known export run; if a newer export run
    exists but an older snapshot is still in use, that is a stale
    bulk-export snapshot.
    """
    findings = []
    prior_runs = [h for h in history if _parse_run_timestamp(h.get("timestamp", ""))]
    current_ts = _parse_run_timestamp(current.get("timestamp", ""))
    if current_ts is None or not prior_runs:
        findings.append({"rule_id": "RUN.EXPORT_STALENESS", "status": "INDETERMINATE",
                          "explanation": "No prior export-run history available to establish a staleness baseline"})
        return build_report(findings)
    most_recent_known = max(_parse_run_timestamp(h["timestamp"]) for h in prior_runs)
    staleness_hours = (most_recent_known - current_ts).total_seconds() / 3600.0
    findings.append({"rule_id": "RUN.EXPORT_STALENESS",
                      "status": "PASS" if staleness_hours <= max_staleness_hours else "FAIL",
                      "source_value": most_recent_known.isoformat(), "target_value": current.get("timestamp", ""),
                      "explanation": "The export snapshot in use must not be older than "
                                     f"{max_staleness_hours}h relative to the most recent known export run"})
    return build_report(findings)


def _provider_role_key(entry: dict) -> str:
    """Identify a provider-directory entry for matching: PractitionerRole
    identifier.value if present, else practitioner id + organization id
    (a PractitionerRole is, by definition, a practitioner acting at one
    organization, so that pair is a reasonable fallback natural key).
    """
    role = entry.get("role", {})
    identifiers = role.get("identifier", [])
    if identifiers and identifiers[0].get("value"):
        return identifiers[0]["value"]
    practitioner_id = (entry.get("practitioner") or {}).get("id", "")
    organization_id = _ref_id_of(role.get("organization"))
    if practitioner_id or organization_id:
        return f"{practitioner_id}/{organization_id}"
    return ""


def _ref_id_of(reference_obj: dict) -> str:
    ref = (reference_obj or {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _location_address_key(entry: dict) -> tuple:
    locations = entry.get("locations", [])
    if not locations:
        return ()
    address = locations[0].get("address", {})
    return (address.get("line", [""])[0] if address.get("line") else "", address.get("city", ""),
            address.get("state", ""), address.get("postalCode", ""))


def _location_phones(entry: dict) -> list:
    phones = []
    for location in entry.get("locations", []):
        for telecom in location.get("telecom", []):
            if telecom.get("system") == "phone" and telecom.get("value"):
                phones.append(telecom["value"])
    return phones


def _has_telehealth_service(entry: dict) -> bool:
    for hs in entry.get("healthcare_services", []):
        codes = [c.get("code", "") for t in hs.get("type", []) for c in t.get("coding", [])]
        if "telehealth" in codes:
            return True
    return False


def compare_many_provider_directory(source: dict, target: dict) -> dict:
    """Reconcile a credentialing system's FHIR Bundle of provider-directory
    resources against the published Da Vinci PDex Plan-Net directory
    Bundle.

    source/target: output of adapters.fhir.parse_fhir_provider_directory_bundle().

    Matching is by PractitionerRole identifier (or, absent one,
    practitioner id + organization id); the prototype does not yet support
    repeated identical keys within a single bundle (such repeats are
    reported as PROVIDER[key].DUPLICATE on the target side).

    SC-123 (practice address changed but not published): matched entries'
    first Location.address must agree -- PROVIDER[key].LOCATION_ADDRESS.

    SC-127 (telehealth/service location omitted): if the source entry has
    a HealthcareService of type "telehealth", the matched target entry
    must too -- PROVIDER[key].TELEHEALTH.

    SC-130 (phone/contact information drift): matched entries' Location
    phone numbers must agree -- PROVIDER[key].PHONE.

    SC-126 (provider duplicated under two organizations): if the same
    practitioner is matched under more than one distinct organization in
    the target batch, reported once as PRACTITIONER[id].ORG_DUPLICATE.

    SC-128 (health plan/network reference broken): every target
    InsurancePlan.network[].reference must resolve to an Organization
    present in the target bundle -- PLAN[id].NETWORK_REF.
    """
    findings = []
    target_by_key: dict = {}
    for entry in target["entries"]:
        key = _provider_role_key(entry)
        if key:
            target_by_key.setdefault(key, []).append(entry)

    source_practitioner_orgs: dict = {}
    target_practitioner_orgs: dict = {}

    for src_entry in source["entries"]:
        key = _provider_role_key(src_entry)
        if not key:
            findings.append({"rule_id": "PROVIDER[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source PractitionerRole has no identifier or practitioner/organization reference to match on"})
            continue
        matches = target_by_key.get(key, [])
        if not matches:
            findings.append({"rule_id": f"PROVIDER[{key}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source PractitionerRole has no corresponding target entry"})
            continue
        if len(matches) > 1:
            findings.append({"rule_id": f"PROVIDER[{key}].DUPLICATE", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": f"Target contains {len(matches)} PractitionerRole entries with this key; expected 1"})
            continue
        target_entry = matches[0]
        for rule in rules_for_domain("provider"):
            result = rule.check(src_entry, target_entry)
            findings.append({
                "rule_id": f"PROVIDER[{key}].{rule.rule_id}",
                "status": result.status,
                "source_value": str(result.source_value),
                "target_value": str(result.target_value),
                "explanation": result.explanation,
            })

        source_address = _location_address_key(src_entry)
        if not source_address:
            findings.append({"rule_id": f"PROVIDER[{key}].LOCATION_ADDRESS", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "Source entry has no Location address"})
        else:
            target_address = _location_address_key(target_entry)
            findings.append({"rule_id": f"PROVIDER[{key}].LOCATION_ADDRESS",
                              "status": "PASS" if source_address == target_address else "FAIL",
                              "source_value": source_address, "target_value": target_address,
                              "explanation": "Practice address preservation (Location.address)"})

        source_telehealth = _has_telehealth_service(src_entry)
        if source_telehealth:
            target_telehealth = _has_telehealth_service(target_entry)
            findings.append({"rule_id": f"PROVIDER[{key}].TELEHEALTH",
                              "status": "PASS" if target_telehealth else "FAIL",
                              "source_value": "telehealth", "target_value": "telehealth" if target_telehealth else "absent",
                              "explanation": "Telehealth service preservation (HealthcareService.type[code=telehealth])"})

        source_phones = _location_phones(src_entry)
        if not source_phones:
            findings.append({"rule_id": f"PROVIDER[{key}].PHONE", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "Source entry has no Location phone"})
        else:
            target_phones = _location_phones(target_entry)
            match = set(source_phones).issubset(set(target_phones))
            findings.append({"rule_id": f"PROVIDER[{key}].PHONE", "status": "PASS" if match else "FAIL",
                              "source_value": source_phones, "target_value": target_phones,
                              "explanation": "Phone/contact preservation (Location.telecom[system=phone].value)"})

        practitioner_id = (target_entry.get("practitioner") or {}).get("id", "")
        if practitioner_id:
            source_org_id = _ref_id_of(src_entry.get("role", {}).get("organization"))
            target_org_id = _ref_id_of(target_entry.get("role", {}).get("organization"))
            source_practitioner_orgs.setdefault(practitioner_id, set()).add(source_org_id)
            target_practitioner_orgs.setdefault(practitioner_id, set()).add(target_org_id)

    for practitioner_id, target_org_ids in target_practitioner_orgs.items():
        source_org_ids = source_practitioner_orgs.get(practitioner_id, set())
        extra_orgs = target_org_ids - source_org_ids
        if extra_orgs:
            findings.append({"rule_id": f"PRACTITIONER[{practitioner_id}].ORG_DUPLICATE", "status": "FAIL",
                              "source_value": sorted(source_org_ids), "target_value": sorted(target_org_ids),
                              "explanation": f"Target directory lists practitioner {practitioner_id} under "
                                             f"organization(s) {sorted(extra_orgs)} not declared by the source "
                                             "credentialing system for this practitioner"})

    target_org_ids = set(target.get("organizations", {}).keys())
    for plan in target.get("insurance_plans", []):
        plan_id = plan.get("id", "")
        network_refs = [_ref_id_of(n) for n in plan.get("network", [])]
        if not network_refs:
            continue
        unresolved = [ref for ref in network_refs if ref not in target_org_ids]
        findings.append({"rule_id": f"PLAN[{plan_id}].NETWORK_REF", "status": "FAIL" if unresolved else "PASS",
                          "source_value": network_refs, "target_value": sorted(target_org_ids),
                          "explanation": "InsurancePlan.network[].reference must resolve to an Organization "
                                         "present in the target bundle"})

    return build_report(findings)


def _attribution_key(patient: dict | None, entity_id: str) -> str:
    """Identify an attribution-list member for matching: Patient
    identifier.value if present, else the raw Patient id referenced by
    Group.member.entity."""
    if patient:
        identifiers = patient.get("identifier", [])
        if identifiers and identifiers[0].get("value"):
            return identifiers[0]["value"]
    return entity_id


def _group_identifier_value(group: dict) -> str:
    identifiers = group.get("identifier", [])
    return identifiers[0].get("value", "") if identifiers else ""


def _group_characteristic_value(group: dict, code: str) -> str:
    for characteristic in group.get("characteristic", []):
        coding = characteristic.get("code", {}).get("coding", [])
        if any(c.get("code") == code for c in coding):
            if "valueBoolean" in characteristic:
                return str(characteristic["valueBoolean"])
            return str(characteristic.get("valueCodeableConcept", characteristic.get("valueQuantity", "")))
    return ""


def _is_deceased(patient: dict | None) -> bool:
    if not patient:
        return False
    return bool(patient.get("deceasedBoolean")) or bool(patient.get("deceasedDateTime"))


def compare_many_member_attribution(source: dict, target: dict) -> dict:
    """Reconcile a payer/ACO's bulk-exported Da Vinci ATR attribution list
    against the provider-side panel returned by the ATR "Member Attribution
    List Reconciliation API".

    source/target: output of adapters.fhir.parse_fhir_attribution_bundle().

    Matching is by Patient identifier (or, absent one, the raw Patient id)
    against every Group.member across all target Groups, since the target
    side may expose one Group (roster) per provider.

    SC-136 (VBC contract identifier lost): Group.identifier of the source's
    primary Group vs. the target Group with the same id (or the first
    target Group if none shares the source's id) -- GROUP[id].CONTRACT_ID.

    SC-140 (risk-adjustment flag dropped): the "risk-adjustment"
    Group.characteristic entry on the same matched Group pair --
    GROUP[id].RISK_ADJUSTMENT.

    SC-135 (attribution list reconciliation count mismatch): member-count
    comparison between the source's primary Group and its matched target
    Group -- CATEGORY[Group].MEMBER_COUNT.

    Per member (MEMBER[key].*):
    SC-131 (missing), SC-132 (DUAL_ATTRIBUTION -- attributed under more
    than one distinct managingEntity across target Groups), SC-133
    (ATTRIBUTION_PERIOD), SC-134 (COVERAGE_REF), SC-137
    (ENCOUNTER_HISTORY), SC-139 (DECEASED -- a deceased source Patient
    must be carried as an inactive member in the target, not silently kept
    active).

    SC-138 (stale bulk-export snapshot) is not handled here: detecting a
    stale $davinci-data-export requires comparing the export timestamp
    against prior export runs, which a single source/target snapshot pair
    does not carry.
    """
    findings = []
    source_group = source["groups"][0]
    source_group_id = source_group.get("id", "")
    target_group = next((g for g in target["groups"] if g.get("id") == source_group_id),
                         target["groups"][0])

    source_contract = _group_identifier_value(source_group)
    target_contract = _group_identifier_value(target_group)
    findings.append({"rule_id": f"GROUP[{source_group_id}].CONTRACT_ID",
                      "status": "PASS" if source_contract == target_contract else "FAIL",
                      "source_value": source_contract, "target_value": target_contract,
                      "explanation": "VBC contract identifier preservation (Group.identifier)"})

    source_risk = _group_characteristic_value(source_group, "risk-adjustment")
    if not source_risk:
        findings.append({"rule_id": f"GROUP[{source_group_id}].RISK_ADJUSTMENT", "status": "INDETERMINATE",
                          "source_value": "", "target_value": "",
                          "explanation": "No source risk-adjustment Group.characteristic supplied"})
    else:
        target_risk = _group_characteristic_value(target_group, "risk-adjustment")
        findings.append({"rule_id": f"GROUP[{source_group_id}].RISK_ADJUSTMENT",
                          "status": "PASS" if source_risk == target_risk else "FAIL",
                          "source_value": source_risk, "target_value": target_risk,
                          "explanation": "Risk-adjustment flag preservation (Group.characteristic"
                                         "[code=risk-adjustment])"})

    source_members = source_group.get("member", [])
    target_members = target_group.get("member", [])
    findings.append({"rule_id": "CATEGORY[Group].MEMBER_COUNT",
                      "status": "PASS" if len(source_members) == len(target_members) else "FAIL",
                      "source_value": len(source_members), "target_value": len(target_members),
                      "explanation": "Attribution list reconciliation count: total member count between "
                                     "the source attribution list and the matched target panel"})

    target_membership: dict = {}
    for group in target["groups"]:
        for member in group.get("member", []):
            patient_id = _ref_id_of(member.get("entity"))
            patient = target["patients"].get(patient_id)
            key = _attribution_key(patient, patient_id)
            if key:
                target_membership.setdefault(key, []).append((group, member, patient))

    for member in source_members:
        patient_id = _ref_id_of(member.get("entity"))
        patient = source["patients"].get(patient_id)
        key = _attribution_key(patient, patient_id)
        if not key:
            findings.append({"rule_id": "MEMBER[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source member has no Patient identifier or id to match on"})
            continue
        matches = target_membership.get(key, [])
        if not matches:
            findings.append({"rule_id": f"MEMBER[{key}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "", "explanation": "Source attribution-list member has no corresponding target member"})
            continue
        distinct_entities = {_ref_id_of(g.get("managingEntity")) for g, _m, _p in matches}
        if len(distinct_entities) > 1:
            findings.append({"rule_id": f"MEMBER[{key}].DUAL_ATTRIBUTION", "status": "FAIL",
                              "source_value": "", "target_value": sorted(distinct_entities),
                              "explanation": f"Target attributes this member to {len(distinct_entities)} "
                                             f"distinct providers/organizations ({sorted(distinct_entities)})"})

        target_group_match, target_member, target_patient = matches[0]

        source_period = member.get("period", {})
        if not source_period.get("start"):
            findings.append({"rule_id": f"MEMBER[{key}].ATTRIBUTION_PERIOD", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "No source Group.member.period.start supplied"})
        else:
            target_period = target_member.get("period", {})
            match = source_period.get("start") == target_period.get("start") and \
                source_period.get("end") == target_period.get("end")
            findings.append({"rule_id": f"MEMBER[{key}].ATTRIBUTION_PERIOD",
                              "status": "PASS" if match else "FAIL",
                              "source_value": source_period, "target_value": target_period,
                              "explanation": "Attribution effective-date preservation (Group.member.period)"})

        source_has_coverage = any(_ref_id_of(c.get("beneficiary")) == patient_id for c in source["coverages"])
        if not source_has_coverage:
            findings.append({"rule_id": f"MEMBER[{key}].COVERAGE_REF", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "No source Coverage resource references this member"})
        else:
            target_patient_id = _ref_id_of(target_member.get("entity"))
            target_has_coverage = any(_ref_id_of(c.get("beneficiary")) == target_patient_id for c in target["coverages"])
            findings.append({"rule_id": f"MEMBER[{key}].COVERAGE_REF",
                              "status": "PASS" if target_has_coverage else "FAIL",
                              "source_value": "present", "target_value": "present" if target_has_coverage else "absent",
                              "explanation": "Coverage linkage preservation (Coverage.beneficiary reference)"})

        source_has_encounter = any(_ref_id_of(e.get("subject")) == patient_id for e in source["encounters"])
        if not source_has_encounter:
            findings.append({"rule_id": f"MEMBER[{key}].ENCOUNTER_HISTORY", "status": "INDETERMINATE",
                              "source_value": "", "target_value": "", "explanation": "No source Encounter resource references this member"})
        else:
            target_patient_id = _ref_id_of(target_member.get("entity"))
            target_has_encounter = any(_ref_id_of(e.get("subject")) == target_patient_id for e in target["encounters"])
            findings.append({"rule_id": f"MEMBER[{key}].ENCOUNTER_HISTORY",
                              "status": "PASS" if target_has_encounter else "FAIL",
                              "source_value": "present", "target_value": "present" if target_has_encounter else "absent",
                              "explanation": "Encounter history inclusion preservation (included Encounter resources)"})

        if _is_deceased(patient):
            target_inactive = target_member.get("inactive") is True
            findings.append({"rule_id": f"MEMBER[{key}].DECEASED",
                              "status": "PASS" if target_inactive else "FAIL",
                              "source_value": "deceased", "target_value": "inactive" if target_inactive else "active",
                              "explanation": "A deceased source Patient must be carried as an inactive "
                                             "Group.member (member.inactive=true) in the target, not left active"})

    return build_report(findings)


def _formulary_item_key(item: dict) -> str:
    identifiers = item.get("identifier", [])
    return identifiers[0].get("value", "") if identifiers else item.get("id", "")


def compare_many_formulary(source: dict, target: dict) -> dict:
    """Reconcile a payer's published Da Vinci PDex US Drug Formulary against
    a second (e.g. re-published, migrated, or member-facing) copy of the
    same formulary.

    source/target: output of adapters.fhir.parse_fhir_formulary_bundle().

    Matching is by FormularyItem.identifier (or raw Basic.id, if absent)
    across all target items.

    Per item (ITEM[key].*): SC-141 (DRUG_TIER), SC-142 (COST_SHARE,
    normal + deductible), SC-143 (PRIOR_AUTH), SC-144 (STEP_THERAPY),
    SC-145 (MISSING -- drug dropped from formulary without a corresponding
    plan/formulary update), SC-146 (RXNORM, via the item's
    medicationReference extension into `medications`), SC-147
    (QUANTITY_LIMIT), SC-148 (FORMULARY_LINK -- the item's
    formularyReference extension must resolve to a Formulary Basic present
    in both bundles), SC-149 (PHARMACY_TYPE).

    SC-150 (formulary effective date stale) is a Formulary-level check
    (FORMULARY[id].EFFECTIVE_DATE): the source Formulary's effectivePeriod
    extension vs. the matched target Formulary's.
    """
    findings = []

    target_items = {}
    for item in target["items"]:
        key = _formulary_item_key(item)
        if key:
            target_items.setdefault(key, []).append(item)

    for item in source["items"]:
        key = _formulary_item_key(item)
        if not key:
            findings.append({"rule_id": "ITEM[?].MATCH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "Source FormularyItem has no identifier or id to match on"})
            continue
        matches = target_items.get(key)
        if not matches:
            findings.append({"rule_id": f"ITEM[{key}].MISSING", "status": "FAIL", "source_value": "",
                              "target_value": "",
                              "explanation": "Drug dropped from formulary: source FormularyItem has no "
                                             "corresponding target item"})
            continue
        target_item = matches[0]

        source_tier = _ext_value(item, "drugTierID")
        target_tier = _ext_value(target_item, "drugTierID")
        findings.append({"rule_id": f"ITEM[{key}].DRUG_TIER",
                          "status": "PASS" if source_tier == target_tier else "FAIL",
                          "source_value": source_tier, "target_value": target_tier,
                          "explanation": "Drug tier preservation (Basic.extension[drugTierID])"})

        source_cost = (_ext_value(item, "costShareNormal"), _ext_value(item, "costShareDeductible"))
        target_cost = (_ext_value(target_item, "costShareNormal"), _ext_value(target_item, "costShareDeductible"))
        findings.append({"rule_id": f"ITEM[{key}].COST_SHARE",
                          "status": "PASS" if source_cost == target_cost else "FAIL",
                          "source_value": source_cost, "target_value": target_cost,
                          "explanation": "Cost-share amount preservation (costShareNormal/costShareDeductible)"})

        source_pa = _ext_value(item, "priorAuthorization")
        target_pa = _ext_value(target_item, "priorAuthorization")
        if source_pa is None:
            findings.append({"rule_id": f"ITEM[{key}].PRIOR_AUTH", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source priorAuthorization extension supplied"})
        else:
            findings.append({"rule_id": f"ITEM[{key}].PRIOR_AUTH",
                              "status": "PASS" if source_pa == target_pa else "FAIL",
                              "source_value": source_pa, "target_value": target_pa,
                              "explanation": "Prior-authorization flag preservation (Basic.extension[priorAuthorization])"})

        source_step = _ext_value(item, "stepTherapyLimit")
        target_step = _ext_value(target_item, "stepTherapyLimit")
        if source_step is None:
            findings.append({"rule_id": f"ITEM[{key}].STEP_THERAPY", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source stepTherapyLimit extension supplied"})
        else:
            findings.append({"rule_id": f"ITEM[{key}].STEP_THERAPY",
                              "status": "PASS" if source_step == target_step else "FAIL",
                              "source_value": source_step, "target_value": target_step,
                              "explanation": "Step-therapy flag preservation (Basic.extension[stepTherapyLimit])"})

        source_qty = _ext_value(item, "quantityLimit")
        target_qty = _ext_value(target_item, "quantityLimit")
        if source_qty is None:
            findings.append({"rule_id": f"ITEM[{key}].QUANTITY_LIMIT", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source quantityLimit extension supplied"})
        else:
            findings.append({"rule_id": f"ITEM[{key}].QUANTITY_LIMIT",
                              "status": "PASS" if source_qty == target_qty else "FAIL",
                              "source_value": source_qty, "target_value": target_qty,
                              "explanation": "Quantity-limit value preservation (Basic.extension[quantityLimit])"})

        source_pharmacy = _ext_value(item, "pharmacyType")
        target_pharmacy = _ext_value(target_item, "pharmacyType")
        if source_pharmacy is None:
            findings.append({"rule_id": f"ITEM[{key}].PHARMACY_TYPE", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source pharmacyType extension supplied"})
        else:
            findings.append({"rule_id": f"ITEM[{key}].PHARMACY_TYPE",
                              "status": "PASS" if source_pharmacy == target_pharmacy else "FAIL",
                              "source_value": source_pharmacy, "target_value": target_pharmacy,
                              "explanation": "Pharmacy network tier preservation (Basic.extension[pharmacyType])"})

        source_med_id = _ref_id_of(_ext_value(item, "medicationReference"))
        source_med = source["medications"].get(source_med_id)
        if not source_med:
            findings.append({"rule_id": f"ITEM[{key}].RXNORM", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source medicationReference resolves to a MedicationKnowledge resource"})
        else:
            target_med_id = _ref_id_of(_ext_value(target_item, "medicationReference"))
            target_med = target["medications"].get(target_med_id)
            source_rxnorm = (source_med.get("code", {}).get("coding") or [{}])[0].get("code", "")
            target_rxnorm = (target_med.get("code", {}).get("coding") or [{}])[0].get("code", "") if target_med else ""
            findings.append({"rule_id": f"ITEM[{key}].RXNORM",
                              "status": "PASS" if source_rxnorm == target_rxnorm else "FAIL",
                              "source_value": source_rxnorm, "target_value": target_rxnorm,
                              "explanation": "RxNorm code preservation (MedicationKnowledge.code)"})

        source_formulary_id = _ref_id_of(_ext_value(item, "formularyReference"))
        source_formulary = source["formularies"].get(source_formulary_id)
        if not source_formulary:
            findings.append({"rule_id": f"ITEM[{key}].FORMULARY_LINK", "status": "INDETERMINATE", "source_value": "",
                              "target_value": "", "explanation": "No source formularyReference resolves to a Formulary Basic resource"})
        else:
            target_formulary_id = _ref_id_of(_ext_value(target_item, "formularyReference"))
            target_formulary = target["formularies"].get(target_formulary_id)
            findings.append({"rule_id": f"ITEM[{key}].FORMULARY_LINK",
                              "status": "PASS" if target_formulary else "FAIL",
                              "source_value": "present", "target_value": "present" if target_formulary else "absent",
                              "explanation": "Formulary-plan linkage preservation (formularyReference resolves "
                                             "to a Formulary Basic resource on both sides)"})

            source_period = _ext_value(source_formulary, "effectivePeriod") or {}
            target_period = _ext_value(target_formulary, "effectivePeriod") or {} if target_formulary else {}
            if not source_period.get("end"):
                findings.append({"rule_id": f"FORMULARY[{source_formulary_id}].EFFECTIVE_DATE", "status": "INDETERMINATE",
                                  "source_value": "", "target_value": "",
                                  "explanation": "No source Formulary effectivePeriod.end supplied"})
            else:
                findings.append({"rule_id": f"FORMULARY[{source_formulary_id}].EFFECTIVE_DATE",
                                  "status": "PASS" if source_period == target_period else "FAIL",
                                  "source_value": source_period, "target_value": target_period,
                                  "explanation": "Formulary effective-period preservation: a target still "
                                                 "showing a stale (unrenewed) effectivePeriod indicates a "
                                                 "stale/unsynced formulary"})

    return build_report(findings)
