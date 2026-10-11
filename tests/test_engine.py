import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from konkord.engine import (
    parse_hl7_obx, load_observation, compare,
    parse_hl7_oru, load_fhir_bundle, compare_many,
    parse_hl7_rde, load_fhir_medication_bundle, compare_many_medications,
    parse_hl7_allergies, load_fhir_allergy_bundle, compare_many_allergies,
    parse_hl7_oru_batch, parse_fhir_bundle_multi, compare_batch,
    parse_hl7_conditions, load_fhir_condition_bundle, compare_many_conditions,
    parse_hl7_procedures, load_fhir_procedure_bundle, compare_many_procedures,
    parse_hl7_coverage, load_fhir_coverage_bundle, compare_many_coverages,
    parse_hl7_documents, load_fhir_document_bundle, compare_many_documents,
    parse_hl7_immunizations, load_fhir_immunization_bundle, compare_many_immunizations,
    parse_hl7_diagnosticreports,
)
from konkord.adapters.fhir import (
    ndjson_to_bundle, load_fhir_json,
    validate_fhir_structure, load_fhir_claim_bundle, load_fhir_claimresponse_bundle,
    load_fhir_eob_bundle, load_fhir_resource_batch, load_fhir_provider_directory_bundle,
    load_fhir_attribution_bundle, load_fhir_formulary_bundle,
    load_fhir_careplan_bundle, load_fhir_servicerequest_bundle,
    load_fhir_goal_bundle, load_fhir_careteam_bundle,
    load_fhir_detectedissue_bundle, load_fhir_task_bundle,
    load_fhir_diagnosticreport_bundle,
)
from konkord.reconciliation.engine import (
    compare_many_prior_authorizations, compare_many_claims, compare_terminology,
    compare_migration_batch, compare_many_provider_directory, compare_many_member_attribution,
    compare_many_formulary, compare_run_history, compare_migration_run_history, compare_export_run_history,
    compare_many_careplans, compare_many_servicerequests,
    compare_many_goals, compare_many_careteams, compare_many_detected_issues,
    compare_many_tasks, compare_many_diagnosticreports,
)
ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_obx((ROOT / "examples/lab.hl7").read_text())
    def test_good(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(result["overall"], "PASS")
        self.assertTrue(all(x["status"] == "PASS" for x in result["checks"]))
    def test_missing_unit(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-bad.json")))
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.UNIT")["status"], "FAIL")
    def test_wrong_value(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        target["valueQuantity"]["value"] = 72
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.VALUE")["status"], "FAIL")
    def test_multiple_obx_rejected(self):
        with self.assertRaises(ValueError):
            parse_hl7_obx("OBX|1|NM|x||1\nOBX|2|NM|y||2")
    def test_precision_changed(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        target["valueQuantity"]["value"] = 7
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.PRECISION")["status"], "FAIL")
    def test_precision_preserved(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.PRECISION")["status"], "PASS")
    def test_numeric_converted_to_text(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        del target["valueQuantity"]
        target["valueString"] = "7.2"
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.VALUE_TYPE")["status"], "FAIL")
    def test_numeric_type_preserved(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.VALUE_TYPE")["status"], "PASS")
    def test_specimen_preserved(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.SPECIMEN")["status"], "PASS")
    def test_specimen_changed(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        target["specimen"]["type"]["text"] = "SER"
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.SPECIMEN")["status"], "FAIL")
    def test_specimen_indeterminate_without_source(self):
        source = dict(self.source)
        source["specimen_type"] = ""
        result = compare(source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.SPECIMEN")["status"], "INDETERMINATE")

    def test_method_preserved(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.METHOD")["status"], "PASS")

    def test_method_changed(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        target["method"]["coding"][0]["code"] = "IA"
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.METHOD")["status"], "FAIL")

    def test_method_indeterminate_without_source(self):
        source = dict(self.source)
        source["method_code"] = ""
        result = compare(source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.METHOD")["status"], "INDETERMINATE")

    def test_performer_preserved(self):
        result = compare(self.source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.PERFORMER")["status"], "PASS")

    def test_performer_changed(self):
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        target["performer"][0]["reference"] = "Practitioner/OTHER999"
        result = compare(self.source, target)
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.PERFORMER")["status"], "FAIL")

    def test_performer_indeterminate_without_source(self):
        source = dict(self.source)
        source["performer_id"] = ""
        result = compare(source, load_observation(str(ROOT / "examples/observation-good.json")))
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "LAB.PERFORMER")["status"], "INDETERMINATE")


class MultiObservationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_oru((ROOT / "examples/panel.hl7").read_text())

    def test_panel_good(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-good.json"))
        result = compare_many(self.source, target)
        # IDENTITY.DECEASED is INDETERMINATE here: the source PID has no
        # deceased indicator, which correctly means "no assertion made"
        # rather than "confirmed not deceased". A single INDETERMINATE
        # finding downgrades the overall status from PASS.
        self.assertEqual(result["overall"], "INDETERMINATE")
        self.assertTrue(all(x["status"] in ("PASS", "INDETERMINATE") for x in result["checks"]))
        identity_checks = {x["rule_id"]: x["status"] for x in result["checks"] if x["rule_id"].startswith("IDENTITY.")}
        self.assertEqual(identity_checks["IDENTITY.MRN"], "PASS")
        self.assertEqual(identity_checks["IDENTITY.BIRTH_DATE"], "PASS")
        self.assertEqual(identity_checks["IDENTITY.NAME"], "PASS")
        self.assertEqual(identity_checks["IDENTITY.DECEASED"], "INDETERMINATE")
        encounter_checks = {x["rule_id"]: x["status"] for x in result["checks"] if x["rule_id"].startswith("ENCOUNTER.")}
        self.assertEqual(encounter_checks["ENCOUNTER.REFERENCE"], "PASS")
        self.assertEqual(encounter_checks["ENCOUNTER.CLASS"], "PASS")
        self.assertEqual(encounter_checks["ENCOUNTER.LOCATION"], "PASS")
        self.assertEqual(encounter_checks["ENCOUNTER.ATTENDING"], "PASS")
        self.assertEqual(encounter_checks["ENCOUNTER.PERIOD_START"], "PASS")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "OBS[2345-7].LAB.METHOD")["status"], "PASS")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "OBS[2345-7].LAB.PERFORMER")["status"], "PASS")

    def test_encounter_mismatches_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-encounter-mismatch.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ENCOUNTER.CLASS"], "FAIL")
        self.assertEqual(checks["ENCOUNTER.LOCATION"], "FAIL")
        self.assertEqual(checks["ENCOUNTER.ATTENDING"], "FAIL")
        self.assertEqual(checks["ENCOUNTER.PERIOD_START"], "FAIL")

    def test_missing_observation_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-missing.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "OBS[2160-0].MISSING")["status"], "FAIL")

    def test_duplicate_observation_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-duplicate.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "OBS[2345-7].DUPLICATE")["status"], "FAIL")

    def test_bad_patient_reference_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-bad-patient.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "PATIENT.REFERENCE")["status"], "FAIL")

    def test_no_pid_segment_patient_is_none(self):
        parsed = parse_hl7_oru("MSH|^~\\&|a|b|c|d|20260101||ORU^R01|1|P|2.5\nOBX|1|NM|2345-7^Glucose^LN||95|mg/dL|70-99|N|||F")
        self.assertIsNone(parsed["patient"])
        self.assertEqual(len(parsed["observations"]), 1)

    def test_identity_mismatches_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-identity-mismatch.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["IDENTITY.MRN"], "FAIL")
        self.assertEqual(checks["IDENTITY.BIRTH_DATE"], "FAIL")
        self.assertEqual(checks["IDENTITY.NAME"], "FAIL")
        self.assertEqual(checks["IDENTITY.ASSIGNING_AUTHORITY"], "FAIL")
        self.assertEqual(checks["IDENTITY.DECEASED"], "INDETERMINATE")

    def test_panel_good_from_ndjson(self):
        """`.ndjson` target files (one FHIR resource per line, as produced
        by FHIR Bulk Data Export) must reconcile identically to the
        equivalent single-document `.json` Bundle."""
        target = load_fhir_bundle(str(ROOT / "examples/panel-bundle-good.ndjson"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "INDETERMINATE")
        self.assertTrue(all(x["status"] in ("PASS", "INDETERMINATE") for x in result["checks"]))


class NdjsonAdapterTests(unittest.TestCase):
    def test_ndjson_to_bundle_wraps_each_line_as_an_entry(self):
        text = '{"resourceType": "Patient", "id": "p1"}\n\n{"resourceType": "Observation", "id": "o1"}\n'
        bundle = ndjson_to_bundle(text)
        self.assertEqual(bundle["resourceType"], "Bundle")
        resource_types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        self.assertEqual(resource_types, ["Patient", "Observation"])

    def test_ndjson_to_bundle_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            ndjson_to_bundle("\n\n   \n")

    def test_ndjson_to_bundle_reports_bad_line_number(self):
        with self.assertRaises(ValueError) as ctx:
            ndjson_to_bundle('{"resourceType": "Patient"}\nnot json\n')
        self.assertIn("line 2", str(ctx.exception))

    def test_load_fhir_json_dispatches_on_extension(self):
        ndjson_bundle = load_fhir_json(str(ROOT / "examples/panel-bundle-good.ndjson"))
        json_bundle = load_fhir_json(str(ROOT / "examples/panel-bundle-good.json"))
        self.assertEqual(ndjson_bundle["resourceType"], "Bundle")
        self.assertEqual(len(ndjson_bundle["entry"]), len(json_bundle["entry"]))


class BatchReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_groups = parse_hl7_oru_batch((ROOT / "examples/panel-batch.hl7").read_text())
        with open(ROOT / "examples/panel-batch-bundle-good.json") as f:
            cls.target_groups = parse_fhir_bundle_multi(json.load(f))

    def test_parses_two_patient_groups_from_batch_message(self):
        self.assertEqual(len(self.source_groups), 2)
        self.assertEqual(self.source_groups[0]["patient"]["id"], "SYNTH002")
        self.assertEqual(self.source_groups[1]["patient"]["id"], "SYNTH003")
        self.assertEqual(len(self.source_groups[0]["observations"]), 2)
        self.assertEqual(len(self.source_groups[1]["observations"]), 1)

    def test_parses_two_patient_groups_from_bundle(self):
        self.assertEqual(len(self.target_groups), 2)
        mrns = {g["patient"]["id"] for g in self.target_groups}
        self.assertEqual(mrns, {"pat-synth002", "pat-synth003"})

    def test_batch_reconciliation_matches_by_mrn(self):
        result = compare_batch(self.source_groups, self.target_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH002].OBS[2345-7].LAB.VALUE"], "PASS")
        self.assertEqual(checks["PATIENT[SYNTH003].OBS[2345-7].LAB.VALUE"], "PASS")
        self.assertNotIn("PATIENT[SYNTH002].MATCH", checks)
        self.assertNotIn("PATIENT[SYNTH003].MATCH", checks)

    def test_batch_reports_unmatched_source_patient(self):
        extra_source = list(self.source_groups) + [{
            "patient": {"id": "SYNTH999"}, "encounter": None, "observations": [],
        }]
        result = compare_batch(extra_source, self.target_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH999].MATCH"], "FAIL")

    def test_batch_reports_unmatched_target_patient(self):
        extra_target = list(self.target_groups) + [{
            "patient": {"id": "pat-synth999", "identifier": [{
                "type": {"coding": [{"code": "MR"}]}, "value": "SYNTH998"}]},
            "encounter": None, "observations": [],
        }]
        result = compare_batch(self.source_groups, extra_target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH998].MATCH"], "WARN")

    def test_identifier_collision_detected_when_two_target_patients_share_mrn(self):
        # SC-019: two distinct target Patient resources both carry MRN SYNTH002.
        colliding_target = {
            "patient": {"id": "pat-duplicate", "identifier": [{
                "type": {"coding": [{"code": "MR"}]}, "value": "SYNTH002"}]},
            "encounter": None, "observations": [],
        }
        result = compare_batch(self.source_groups, list(self.target_groups) + [colliding_target])
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH002].IDENTITY.COLLISION"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_merge_detected_when_one_target_patient_carries_two_source_mrns(self):
        # SC-014: a single target Patient carries identifiers for two distinct
        # source MRNs, so both source patient groups resolve to the same
        # target Patient resource.
        merged_patient = {
            "id": "pat-merged",
            "identifier": [
                {"type": {"coding": [{"code": "MR"}]}, "value": "SYNTH002"},
                {"type": {"coding": [{"code": "MR"}]}, "value": "SYNTH003"},
            ],
        }
        all_observations = [obs for g in self.target_groups for obs in g["observations"]]
        merged_target_groups = [{"patient": merged_patient, "encounter": None, "observations": all_observations}]
        result = compare_batch(self.source_groups, merged_target_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[pat-merged].IDENTITY.MERGE"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_duplicate_encounter_detected_when_patient_has_two_encounters(self):
        # SC-029: the matched target Patient has two Encounter resources
        # instead of one.
        duplicated_groups = [dict(g) for g in self.target_groups]
        duplicated_groups[0]["all_encounters"] = [
            duplicated_groups[0]["encounter"],
            {"id": "enc-extra-duplicate"},
        ]
        result = compare_batch(self.source_groups, duplicated_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        mrn = self.source_groups[0]["patient"]["id"]
        self.assertEqual(checks[f"PATIENT[{mrn}].ENCOUNTER.DUPLICATE"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_wrong_patient_assignment_detected(self):
        # SC-011: target Patient pat-synth002 (matched to MRN SYNTH002) carries
        # the demographic identity of the *other* source patient (SYNTH003),
        # while pat-synth003 still correctly owns that identity.
        swapped_groups = [dict(g) for g in self.target_groups]
        swapped_groups[0] = dict(swapped_groups[0])
        swapped_groups[0]["patient"] = dict(swapped_groups[0]["patient"])
        swapped_groups[0]["patient"]["name"] = [{"family": "Second", "given": ["Patient"]}]
        swapped_groups[0]["patient"]["birthDate"] = "1975-05-12"
        result = compare_batch(self.source_groups, swapped_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH002].IDENTITY.WRONG_PATIENT_ASSIGNMENT"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_patient_split_detected(self):
        # SC-015: a third target Patient (different MRN/id) carries the same
        # demographic identity as source patient SYNTH002.
        split_target = {
            "patient": {
                "id": "pat-synth002-dup",
                "name": [{"family": "Example", "given": ["Patient"]}],
                "birthDate": "1980-01-01",
                "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "SYNTH997"}],
            },
            "encounter": None, "observations": [],
        }
        result = compare_batch(self.source_groups, list(self.target_groups) + [split_target])
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH002].IDENTITY.SPLIT"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_wrong_encounter_association_detected(self):
        # SC-024: the Encounter attached to target Patient pat-synth002
        # (matched by MRN SYNTH002, visit number VISIT002) actually carries
        # the visit number belonging to source patient SYNTH003 (VISIT003).
        swapped_groups = [dict(g) for g in self.target_groups]
        swapped_groups[0] = dict(swapped_groups[0])
        swapped_groups[0]["encounter"] = dict(swapped_groups[0]["encounter"])
        swapped_groups[0]["encounter"]["identifier"] = [{"value": "VISIT003"}]
        result = compare_batch(self.source_groups, swapped_groups)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PATIENT[SYNTH002].ENCOUNTER.WRONG_PATIENT_ASSIGNMENT"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")


class MedicationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_rde((ROOT / "examples/medication.hl7").read_text())

    def test_medication_good(self):
        target = load_fhir_medication_bundle(str(ROOT / "examples/medication-bundle-good.json"))
        result = compare_many_medications(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["MED[197361].MEDICATION.CODE"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.DOSE_AMOUNT"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.DOSE_UNIT"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.ROUTE"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.FREQUENCY"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.STATUS"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.DATE"], "PASS")
        self.assertEqual(checks["MED[197361].MEDICATION.REFILLS"], "PASS")
        self.assertEqual(checks["PATIENT.REFERENCE"], "PASS")

    def test_medication_mismatches_detected(self):
        target = load_fhir_medication_bundle(str(ROOT / "examples/medication-bundle-mismatch.json"))
        result = compare_many_medications(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["MED[197361].MEDICATION.DOSE_AMOUNT"], "FAIL")
        self.assertEqual(checks["MED[197361].MEDICATION.ROUTE"], "FAIL")
        self.assertEqual(checks["MED[197361].MEDICATION.FREQUENCY"], "FAIL")
        self.assertEqual(checks["MED[197361].MEDICATION.STATUS"], "FAIL")
        self.assertEqual(checks["MED[197361].MEDICATION.REFILLS"], "FAIL")

    def test_medication_missing_detected(self):
        target = load_fhir_medication_bundle(str(ROOT / "examples/medication-bundle-missing.json"))
        result = compare_many_medications(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "MED[197361].MISSING")["status"], "FAIL")

    def test_medication_request_confused_with_administration_detected(self):
        # SC-040: the order's code only matches a MedicationAdministration
        # in the target, not a MedicationRequest.
        target = load_fhir_medication_bundle(str(ROOT / "examples/medication-bundle-administration-only.json"))
        result = compare_many_medications(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["MED[197361].REQUEST_CONFUSED_WITH_ADMINISTRATION"], "FAIL")
        self.assertNotIn("MED[197361].MISSING", checks)

    def test_parse_hl7_rde_requires_rxe(self):
        with self.assertRaises(ValueError):
            parse_hl7_rde("MSH|^~\\&|a|b|c|d|20260101||RDE^O11|1|P|2.5\nPID|1||X^^^T^MR")


class AllergyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_allergies((ROOT / "examples/allergy.hl7").read_text())

    def test_allergy_good(self):
        target = load_fhir_allergy_bundle(str(ROOT / "examples/allergy-bundle-good.json"))
        result = compare_many_allergies(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.CODE"], "PASS")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.REACTION"], "PASS")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.SEVERITY"], "PASS")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.ONSET_DATE"], "PASS")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.CLINICAL_STATUS"], "PASS")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.VERIFICATION_STATUS"], "PASS")
        self.assertEqual(checks["PATIENT.REFERENCE"], "PASS")

    def test_allergy_mismatches_detected(self):
        target = load_fhir_allergy_bundle(str(ROOT / "examples/allergy-bundle-mismatch.json"))
        result = compare_many_allergies(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.REACTION"], "FAIL")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.SEVERITY"], "FAIL")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.ONSET_DATE"], "FAIL")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.CLINICAL_STATUS"], "FAIL")
        self.assertEqual(checks["ALLERGY[1191].ALLERGY.VERIFICATION_STATUS"], "FAIL")

    def test_allergy_missing_detected(self):
        target = load_fhir_allergy_bundle(str(ROOT / "examples/allergy-bundle-missing.json"))
        result = compare_many_allergies(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "ALLERGY[1191].MISSING")["status"], "FAIL")

    def test_parse_hl7_allergies_requires_al1(self):
        with self.assertRaises(ValueError):
            parse_hl7_allergies("MSH|^~\\&|a|b|c|d|20260101||ADT^A04|1|P|2.5\nPID|1||X^^^T^MR")

    def test_no_known_allergy_assertion_lost_detected(self):
        # SC-047: source asserts "no known allergies" (NKA sentinel), but the
        # target bundle contains a real allergen entry instead.
        source = {"patient": {"id": "X"}, "allergies": [{"code": "NKA", "reactions": []}]}
        target = {
            "patient": {"id": "X"},
            "allergy_intolerances": [
                {"code": {"coding": [{"code": "1191"}]}, "patient": {"reference": "Patient/X"}},
            ],
        }
        result = compare_many_allergies(source, target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY.NO_KNOWN_ALLERGY_ASSERTION"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_no_known_allergy_assertion_introduced_detected(self):
        # SC-047 (converse): source has a real allergen, but target instead
        # asserts "no known allergies".
        source = {"patient": {"id": "X"}, "allergies": [{"code": "1191", "reactions": []}]}
        target = {
            "patient": {"id": "X"},
            "allergy_intolerances": [
                {"code": {"coding": [{"code": "716186003"}]}, "patient": {"reference": "Patient/X"}},
            ],
        }
        result = compare_many_allergies(source, target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY.NO_KNOWN_ALLERGY_ASSERTION"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")

    def test_reaction_linked_to_wrong_substance_detected(self):
        # SC-049: two allergies in the same message/bundle, but the reaction
        # manifestations were swapped between the two target AllergyIntolerances.
        source = {
            "patient": {"id": "X"},
            "allergies": [
                {"code": "1191", "reactions": ["Hives"]},
                {"code": "7980", "reactions": ["Anaphylaxis"]},
            ],
        }
        target = {
            "patient": {"id": "X"},
            "allergy_intolerances": [
                {
                    "code": {"coding": [{"code": "1191"}]},
                    "reaction": [{"manifestation": [{"text": "Anaphylaxis"}]}],
                    "patient": {"reference": "Patient/X"},
                },
                {
                    "code": {"coding": [{"code": "7980"}]},
                    "reaction": [{"manifestation": [{"text": "Hives"}]}],
                    "patient": {"reference": "Patient/X"},
                },
            ],
        }
        result = compare_many_allergies(source, target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY[1191].REACTION_LINKED_TO_WRONG_SUBSTANCE"], "FAIL")
        self.assertEqual(checks["ALLERGY[7980].REACTION_LINKED_TO_WRONG_SUBSTANCE"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")


class ImmunizationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_immunizations((ROOT / "examples/immunization.hl7").read_text())

    def test_immunization_good(self):
        target = load_fhir_immunization_bundle(str(ROOT / "examples/immunization-bundle-good.json"))
        result = compare_many_immunizations(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.VACCINE_CODE"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.DATE"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.LOT_NUMBER"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.EXPIRATION_DATE"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.DOSE_AMOUNT"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.DOSE_UNIT"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.MANUFACTURER"], "PASS")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.STATUS"], "PASS")
        self.assertEqual(checks["PATIENT.REFERENCE"], "PASS")

    def test_immunization_mismatches_detected(self):
        target = load_fhir_immunization_bundle(str(ROOT / "examples/immunization-bundle-mismatch.json"))
        result = compare_many_immunizations(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.DATE"], "FAIL")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.LOT_NUMBER"], "FAIL")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.EXPIRATION_DATE"], "FAIL")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.DOSE_AMOUNT"], "FAIL")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.MANUFACTURER"], "FAIL")
        self.assertEqual(checks["IMMUNIZATION[08].IMMUNIZATION.STATUS"], "FAIL")

    def test_immunization_missing_detected(self):
        target = load_fhir_immunization_bundle(str(ROOT / "examples/immunization-bundle-missing.json"))
        result = compare_many_immunizations(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "IMMUNIZATION[08].MISSING")["status"], "FAIL")

    def test_parse_hl7_immunizations_requires_rxa(self):
        with self.assertRaises(ValueError):
            parse_hl7_immunizations("MSH|^~\\&|a|b|c|d|20260101||VXU^V04|1|P|2.5\nPID|1||X^^^T^MR")


class SyntheaDerivedFixtureTests(unittest.TestCase):
    """Exercises the same reconciliation scenarios against fixtures derived
    from real MITRE Synthea synthetic patient records (see
    scripts/derive_synthea_fixtures.py), instead of hand-written JSON/HL7.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_oru((ROOT / "examples/panel-synthea.hl7").read_text())

    def test_panel_good_warns_on_absent_interpretation_and_range(self):
        # Real Synthea lab observations in this sample carry no interpretation
        # flag or reference range, so the honest result is WARN, not PASS/FAIL.
        target = load_fhir_bundle(str(ROOT / "examples/panel-synthea-bundle-good.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "WARN")
        self.assertTrue(all(x["status"] in ("PASS", "WARN", "INDETERMINATE") for x in result["checks"]))
        # Basic Metabolic Panel (8 analytes), derived from whichever of them
        # the real Synthea patient actually has recorded.
        self.assertEqual(len(self.source["observations"]), 8)

    def test_missing_observation_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-synthea-bundle-missing.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")

    def test_duplicate_observation_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-synthea-bundle-duplicate.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")

    def test_bad_patient_reference_detected(self):
        target = load_fhir_bundle(str(ROOT / "examples/panel-synthea-bundle-bad-patient.json"))
        result = compare_many(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "PATIENT.REFERENCE")["status"], "FAIL")

    def test_medication_good_no_failures(self):
        # Real Synthea MedicationRequest in this sample has no dose unit or
        # route captured on the HL7v2 side (the source record doesn't carry
        # those fields), so the honest result is INDETERMINATE, not PASS.
        source = parse_hl7_rde((ROOT / "examples/medication-synthea.hl7").read_text())
        target = load_fhir_medication_bundle(str(ROOT / "examples/medication-synthea-bundle-good.json"))
        result = compare_many_medications(source, target)
        self.assertEqual(result["overall"], "INDETERMINATE")
        self.assertTrue(all(x["status"] in ("PASS", "INDETERMINATE") for x in result["checks"]))
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["MED[309097].MEDICATION.CODE"], "PASS")
        self.assertEqual(checks["MED[309097].MEDICATION.DOSE_AMOUNT"], "PASS")
        self.assertEqual(checks["MED[309097].MEDICATION.FREQUENCY"], "PASS")
        self.assertEqual(checks["MED[309097].MEDICATION.STATUS"], "PASS")
        self.assertEqual(checks["MED[309097].MEDICATION.DATE"], "PASS")

    def test_allergy_good_no_failures(self):
        # Real Synthea allergy HL7v2 in this sample carries no ZAL
        # (site-defined) segment, so clinical/verification status have no
        # source data; the honest result is INDETERMINATE, not PASS.
        source = parse_hl7_allergies((ROOT / "examples/allergy-synthea.hl7").read_text())
        target = load_fhir_allergy_bundle(str(ROOT / "examples/allergy-synthea-bundle-good.json"))
        result = compare_many_allergies(source, target)
        self.assertEqual(result["overall"], "INDETERMINATE")
        self.assertTrue(all(x["status"] in ("PASS", "INDETERMINATE") for x in result["checks"]))
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.CODE"], "PASS")
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.REACTION"], "PASS")
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.SEVERITY"], "PASS")
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.ONSET_DATE"], "PASS")
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.CLINICAL_STATUS"], "INDETERMINATE")
        self.assertEqual(checks["ALLERGY[264287008].ALLERGY.VERIFICATION_STATUS"], "INDETERMINATE")


class RepositoryCorrelationHistoryTests(unittest.TestCase):
    """list_jobs_by_correlation() is what lets the API assemble run history
    from the server's own persisted jobs instead of requiring the caller to
    resubmit old bundles: same correlation_id => same pipeline's history."""

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile

        cls._tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp_db.close()
        os.environ["KONKORD_DATABASE_URL"] = f"sqlite:///{cls._tmp_db.name}"
        try:
            import konkord.db.session as session_module
            import importlib

            importlib.reload(session_module)
            import konkord.db.repository as repository_module

            importlib.reload(repository_module)
        except ImportError as exc:  # pragma: no cover - db extra not installed
            raise unittest.SkipTest(f"db extra not installed: {exc}")
        cls.session_module = session_module
        cls.repository = repository_module
        cls.session_module.init_db()

    @classmethod
    def tearDownClass(cls):
        import os

        os.environ.pop("KONKORD_DATABASE_URL", None)
        os.unlink(cls._tmp_db.name)

    @staticmethod
    def _report(status="PASS"):
        return {"schema_version": "1.0", "overall": status, "disclaimer": "",
                "checks": [{"rule_id": "RULE[0]", "status": status, "source_value": "", "target_value": "",
                            "explanation": ""}]}

    def test_list_jobs_by_correlation_filters_and_orders_oldest_first(self):
        db = self.session_module.SessionLocal()
        try:
            j1 = self.repository.save_job_report(db, self._report("PASS"), correlation_id="pipeline-a")
            j2 = self.repository.save_job_report(db, self._report("FAIL"), correlation_id="pipeline-a")
            self.repository.save_job_report(db, self._report("PASS"), correlation_id="pipeline-b")
            history = self.repository.list_jobs_by_correlation(db, "pipeline-a")
            self.assertEqual([j.id for j in history], [j1.id, j2.id])
            self.assertTrue(all(j.correlation_id == "pipeline-a" for j in history))
        finally:
            db.close()

    def test_before_job_id_excludes_current_job(self):
        db = self.session_module.SessionLocal()
        try:
            j1 = self.repository.save_job_report(db, self._report("PASS"), correlation_id="pipeline-c")
            j2 = self.repository.save_job_report(db, self._report("PASS"), correlation_id="pipeline-c")
            history = self.repository.list_jobs_by_correlation(db, "pipeline-c", before_job_id=j2.id)
            self.assertEqual([j.id for j in history], [j1.id])
        finally:
            db.close()


class FhirStructuralValidationTests(unittest.TestCase):
    """Real FHIR R4B structural validation (via `fhir.resources`), used as a
    non-blocking advisory check surfaced to callers as warnings.
    """

    def test_conformant_bundle_has_no_warnings(self):
        bundle = json.loads((ROOT / "examples" / "panel-bundle-good.json").read_text())
        self.assertEqual(validate_fhir_structure(bundle), [])

    def test_non_conformant_bundle_reports_warnings(self):
        # authoredOn without a timezone offset violates the FHIR R4 dateTime regex.
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "status": "active",
                        "intent": "order",
                        "subject": {"reference": "Patient/PAT1"},
                        "authoredOn": "2026-10-09T10:00:00",
                    }
                }
            ],
        }
        warnings = validate_fhir_structure(bundle)
        self.assertTrue(warnings)
        self.assertTrue(any("authoredOn" in w for w in warnings))

    def test_unknown_resource_type_returns_no_warnings(self):
        self.assertEqual(validate_fhir_structure({"resourceType": "Provenance"}), [])


class ConditionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_conditions((ROOT / "examples/clinical.hl7").read_text())

    def test_condition_good(self):
        target = load_fhir_condition_bundle(str(ROOT / "examples/condition-bundle-good.json"))
        result = compare_many_conditions(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CONDITION[44054006].CONDITION.CODE"], "PASS")
        self.assertEqual(checks["CONDITION[44054006].CONDITION.ONSET_DATE"], "PASS")
        self.assertEqual(checks["CONDITION[44054006].ENCOUNTER.REFERENCE"], "PASS")
        self.assertEqual(checks["CONDITION[44054006].CONDITION.CLINICAL_STATUS"], "PASS")
        self.assertEqual(checks["CONDITION[44054006].CONDITION.VERIFICATION_STATUS"], "PASS")
        self.assertEqual(checks["PATIENT.REFERENCE"], "PASS")

    def test_condition_mismatches_detected(self):
        target = load_fhir_condition_bundle(str(ROOT / "examples/condition-bundle-mismatch.json"))
        result = compare_many_conditions(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CONDITION[44054006].CONDITION.ONSET_DATE"], "FAIL")
        self.assertEqual(checks["CONDITION[44054006].ENCOUNTER.REFERENCE"], "FAIL")
        self.assertEqual(checks["CONDITION[44054006].CONDITION.CLINICAL_STATUS"], "FAIL")
        self.assertEqual(checks["CONDITION[44054006].CONDITION.VERIFICATION_STATUS"], "FAIL")

    def test_condition_missing_detected(self):
        target = load_fhir_condition_bundle(str(ROOT / "examples/condition-bundle-missing.json"))
        result = compare_many_conditions(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "CONDITION[44054006].MISSING")["status"], "FAIL")

    def test_parse_hl7_conditions_requires_dg1(self):
        with self.assertRaises(ValueError):
            parse_hl7_conditions("MSH|^~\\&|a|b|c|d|20260101||ADT^A01|1|P|2.5\nPID|1||X^^^T^MR")


class ProcedureEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_procedures((ROOT / "examples/procedure.hl7").read_text())

    def test_procedure_good(self):
        target = load_fhir_procedure_bundle(str(ROOT / "examples/procedure-bundle-good.json"))
        result = compare_many_procedures(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.CODE"], "PASS")
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.PERFORMER"], "PASS")
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.DATE"], "PASS")
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.STATUS"], "PASS")
        self.assertEqual(checks["PATIENT.REFERENCE"], "PASS")

    def test_procedure_mismatches_detected(self):
        target = load_fhir_procedure_bundle(str(ROOT / "examples/procedure-bundle-mismatch.json"))
        result = compare_many_procedures(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.PERFORMER"], "FAIL")
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.DATE"], "FAIL")
        self.assertEqual(checks["PROCEDURE[80146002].PROCEDURE.STATUS"], "FAIL")

    def test_procedure_missing_detected(self):
        target = load_fhir_procedure_bundle(str(ROOT / "examples/procedure-bundle-missing.json"))
        result = compare_many_procedures(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "PROCEDURE[80146002].MISSING")["status"], "FAIL")

    def test_parse_hl7_procedures_requires_pr1(self):
        with self.assertRaises(ValueError):
            parse_hl7_procedures("MSH|^~\\&|a|b|c|d|20260101||ADT^A01|1|P|2.5\nPID|1||X^^^T^MR")


class CoverageEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_coverage((ROOT / "examples/coverage.hl7").read_text())

    def test_coverage_good(self):
        target = load_fhir_coverage_bundle(str(ROOT / "examples/coverage-bundle-good.json"))
        result = compare_many_coverages(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.EFFECTIVE_DATE"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.EXPIRATION_DATE"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.RELATIONSHIP"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.MEMBER_ID"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.PAYOR_REFERENCE"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.GROUP_NUMBER"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.PRIORITY"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.STATUS"], "PASS")
        self.assertEqual(checks["COVERAGE[MEMBER7788].BENEFICIARY"], "PASS")

    def test_coverage_mismatches_detected(self):
        target = load_fhir_coverage_bundle(str(ROOT / "examples/coverage-bundle-mismatch.json"))
        result = compare_many_coverages(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.RELATIONSHIP"], "FAIL")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.PAYOR_REFERENCE"], "FAIL")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.GROUP_NUMBER"], "FAIL")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.PRIORITY"], "FAIL")
        self.assertEqual(checks["COVERAGE[MEMBER7788].COVERAGE.STATUS"], "FAIL")
        self.assertEqual(checks["COVERAGE[MEMBER7788].BENEFICIARY"], "FAIL")

    def test_coverage_missing_detected(self):
        target = load_fhir_coverage_bundle(str(ROOT / "examples/coverage-bundle-missing.json"))
        result = compare_many_coverages(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "COVERAGE[MEMBER7788].MISSING")["status"], "FAIL")

    def test_parse_hl7_coverage_requires_in1(self):
        with self.assertRaises(ValueError):
            parse_hl7_coverage("MSH|^~\\&|a|b|c|d|20260101||ADT^A01|1|P|2.5\nPID|1||X^^^T^MR")


class PriorAuthorizationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_claim_bundle(str(ROOT / "examples/priorauth-claim-bundle.json"))

    def test_priorauth_good(self):
        target = load_fhir_claimresponse_bundle(str(ROOT / "examples/priorauth-claimresponse-bundle-good.json"))
        result = compare_many_prior_authorizations(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.STATUS"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.AUTHORIZATION_ID"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.APPROVED_QUANTITY"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.VALIDITY_PERIOD"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.DECISION_REASON"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.WORKFLOW_SYNC"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].ITEM[1].SERVICE_CODE"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].SUPPORTING_INFO"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].SERVICE_MISMATCH"], "PASS")
        self.assertEqual(checks["PRIORAUTH[PA-1001].COVERAGE_LINK"], "PASS")

    def test_priorauth_mismatches_detected(self):
        target = load_fhir_claimresponse_bundle(str(ROOT / "examples/priorauth-claimresponse-bundle-mismatch.json"))
        result = compare_many_prior_authorizations(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.STATUS"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.APPROVED_QUANTITY"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.VALIDITY_PERIOD"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].PRIORAUTH.DECISION_REASON"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].COVERAGE_LINK"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].ITEM[1].SERVICE_CODE"], "FAIL")
        self.assertEqual(checks["PRIORAUTH[PA-1001].SUPPORTING_INFO"], "FAIL")

    def test_priorauth_missing_detected(self):
        target = load_fhir_claimresponse_bundle(str(ROOT / "examples/priorauth-claimresponse-bundle-missing.json"))
        result = compare_many_prior_authorizations(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "PRIORAUTH[PA-1001].MISSING")["status"], "FAIL")

    def test_parse_fhir_claim_bundle_requires_claim(self):
        with self.assertRaises(ValueError):
            load_fhir_claim_bundle(str(ROOT / "examples/coverage-bundle-good.json"))


class ClaimEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_claim_bundle(str(ROOT / "examples/claim-bundle.json"))

    def test_claim_good(self):
        target = load_fhir_eob_bundle(str(ROOT / "examples/eob-bundle-good.json"))
        result = compare_many_claims(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.STATUS"], "PASS")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.BILLED_AMOUNT"], "PASS")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.CURRENCY"], "PASS")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.DIAGNOSIS_LINKAGE"], "PASS")
        self.assertEqual(checks["CLAIM[CLM-2001].LINE_MISMATCH"], "PASS")
        self.assertEqual(checks["CLAIM[CLM-2001].EOB_LINK"], "PASS")

    def test_claim_mismatches_detected(self):
        target = load_fhir_eob_bundle(str(ROOT / "examples/eob-bundle-mismatch.json"))
        result = compare_many_claims(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.STATUS"], "FAIL")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.BILLED_AMOUNT"], "FAIL")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.CURRENCY"], "FAIL")
        self.assertEqual(checks["CLAIM[CLM-2001].CLAIM.DIAGNOSIS_LINKAGE"], "FAIL")
        self.assertEqual(checks["CLAIM[CLM-2001].LINE_MISMATCH"], "FAIL")
        self.assertEqual(checks["CLAIM[CLM-2001].EOB_LINK"], "FAIL")

    def test_claim_missing_detected(self):
        target = load_fhir_eob_bundle(str(ROOT / "examples/eob-bundle-missing.json"))
        result = compare_many_claims(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "CLAIM[CLM-2001].MISSING")["status"], "FAIL")

    def test_parse_fhir_eob_bundle_requires_eob(self):
        with self.assertRaises(ValueError):
            load_fhir_eob_bundle(str(ROOT / "examples/coverage-bundle-good.json"))


class TerminologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_obx((ROOT / "examples/terminology.hl7").read_text())

    def test_terminology_good(self):
        target = load_observation(str(ROOT / "examples/terminology-observation-good.json"))
        result = compare_terminology(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["TERMINOLOGY.SYSTEM"], "PASS")
        self.assertEqual(checks["TERMINOLOGY.VERSION"], "PASS")
        self.assertEqual(checks["TERMINOLOGY.DISPLAY"], "PASS")
        self.assertEqual(checks["TERMINOLOGY.MULTI_CODING"], "PASS")

    def test_terminology_mismatch(self):
        target = load_observation(str(ROOT / "examples/terminology-observation-mismatch.json"))
        result = compare_terminology(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["TERMINOLOGY.SYSTEM"], "FAIL")
        self.assertEqual(checks["TERMINOLOGY.VERSION"], "FAIL")
        self.assertEqual(checks["TERMINOLOGY.DISPLAY"], "FAIL")
        self.assertEqual(checks["TERMINOLOGY.MULTI_CODING"], "FAIL")

    def test_terminology_local_mapping(self):
        source = {"alt_code": "HGBA1C"}
        target = {"code": {"coding": [{"code": "4548-4"}]}}
        from konkord.rules.terminology_observation import check_local_mapping
        self.assertEqual(check_local_mapping(source, target).status, "PASS")
        self.assertEqual(check_local_mapping(source, {"code": {"coding": [{"code": "9999-9"}]}}).status, "FAIL")
        self.assertEqual(check_local_mapping({"alt_code": "UNKNOWN"}, target).status, "INDETERMINATE")

    def test_terminology_valueset_binding(self):
        from konkord.rules.terminology_observation import check_valueset_binding
        source = {"code": "4548-4"}
        good = {"code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]}}
        bad = {"code": {"coding": [{"system": "http://loinc.org", "code": "99999-9"}]}}
        self.assertEqual(check_valueset_binding(source, good).status, "PASS")
        self.assertEqual(check_valueset_binding(source, bad).status, "FAIL")

    def test_terminology_ucum_conversion(self):
        from konkord.rules.terminology_observation import check_ucum_conversion
        source = {"value": "90", "unit": "mg/dL"}
        good = {"valueQuantity": {"value": 90, "code": "mg/dL"}}
        bad = {"valueQuantity": {"value": 50, "code": "mg/dL"}}
        self.assertEqual(check_ucum_conversion(source, good).status, "PASS")
        self.assertEqual(check_ucum_conversion(source, bad).status, "FAIL")
        mmol_source = {"value": "5", "unit": "mmol/L"}
        mmol_match = {"valueQuantity": {"value": 90, "code": "mg/dL"}}
        self.assertEqual(check_ucum_conversion(mmol_source, mmol_match).status, "PASS")

    def test_terminology_deprecated_code(self):
        from konkord.rules.terminology_observation import check_deprecated_code
        source = {"code": "2345-7"}
        current = {"code": {"coding": [{"system": "http://loinc.org", "code": "48643-1"}]}}
        deprecated = {"code": {"coding": [{"system": "http://loinc.org", "code": "2345-7"}]}}
        self.assertEqual(check_deprecated_code(source, current).status, "PASS")
        self.assertEqual(check_deprecated_code(source, deprecated).status, "FAIL")

    def test_terminology_snomed_specificity(self):
        from konkord.rules.terminology_observation import check_snomed_specificity
        source = {"code": "17856-6"}
        specific = {"code": {"coding": [{"code": "17856-6"}]}}
        widened = {"code": {"coding": [{"code": "444619008"}]}}
        self.assertEqual(check_snomed_specificity(source, specific).status, "PASS")
        self.assertEqual(check_snomed_specificity(source, widened).status, "FAIL")

    def test_terminology_element_meaning_moved(self):
        from konkord.rules.terminology_observation import check_element_meaning_moved
        source = {"code": "4548-4", "display": "Hemoglobin A1c", "alt_text": "HbA1c panel note"}
        correct = {"code": {"coding": [{"code": "4548-4", "display": "Hemoglobin A1c"}]}}
        moved = {"code": {"coding": [{"code": "4548-4", "display": "HbA1c panel note"}]}}
        self.assertEqual(check_element_meaning_moved(source, correct).status, "PASS")
        self.assertEqual(check_element_meaning_moved(source, moved).status, "FAIL")
        self.assertEqual(check_element_meaning_moved({"display": "X"}, correct).status, "INDETERMINATE")

    def test_terminology_no_source_metadata_indeterminate(self):
        bare_source = parse_hl7_obx((ROOT / "examples/lab.hl7").read_text())
        target = load_observation(str(ROOT / "examples/observation-good.json"))
        result = compare_terminology(bare_source, target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["TERMINOLOGY.VERSION"], "INDETERMINATE")
        self.assertEqual(checks["TERMINOLOGY.MULTI_CODING"], "INDETERMINATE")

    def test_terminology_missing_target(self):
        result = compare_terminology(self.source, None)
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(all(x["status"] == "FAIL" for x in result["checks"]))


class TerminologyProviderOverrideTests(unittest.TestCase):
    """Verifies the pluggable TerminologyProvider: JSON-file overrides are
    merged on top of the bundled defaults, and a custom in-memory provider
    can be installed directly via set_terminology_provider()."""

    def setUp(self):
        from konkord.rules import terminology_provider
        self._module = terminology_provider
        self.addCleanup(terminology_provider.reset_terminology_provider)
        self.addCleanup(self._clear_env)
        terminology_provider.reset_terminology_provider()

    def _clear_env(self):
        import os
        os.environ.pop("KONKORD_TERMINOLOGY_CONFIG", None)

    def test_json_override_extends_and_overrides_bundled_defaults(self):
        import os
        import tempfile
        from konkord.rules.terminology_observation import (
            check_local_mapping, check_ucum_conversion,
        )

        override = {
            # New local-code mapping not present in the bundled defaults.
            "local_code_map": {"CUSTOM1": "9999-9"},
            # Override an existing UCUM conversion factor.
            "ucum_conversion": {"mmol/L": ["mg/dL", 20.0]},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(override, f)
            config_path = f.name
        self.addCleanup(lambda: os.remove(config_path))

        os.environ["KONKORD_TERMINOLOGY_CONFIG"] = config_path
        self._module.reset_terminology_provider()

        # New mapping from the override file is honored.
        result = check_local_mapping(
            {"alt_code": "CUSTOM1"}, {"code": {"coding": [{"code": "9999-9"}]}}
        )
        self.assertEqual(result.status, "PASS")

        # Bundled default mapping (not touched by the override) still works.
        result = check_local_mapping(
            {"alt_code": "HGBA1C"}, {"code": {"coding": [{"code": "4548-4"}]}}
        )
        self.assertEqual(result.status, "PASS")

        # Overridden UCUM factor (20.0 instead of bundled 18.0) is applied.
        result = check_ucum_conversion(
            {"value": "5", "unit": "mmol/L"},
            {"valueQuantity": {"value": 100, "code": "mg/dL"}},
        )
        self.assertEqual(result.status, "PASS")

    def test_custom_provider_can_be_installed_directly(self):
        from konkord.rules.terminology_observation import check_system

        class StubProvider:
            def system_uri(self, coding_system):
                return {"CUSTOM-SYS": "urn:example:custom"}.get(coding_system)

            def canonical_code(self, local_code):
                return None

            def approved_codes(self, system):
                return None

            def ucum_conversion(self, unit):
                return None

            def deprecated_replacement(self, system, code):
                return None

            def snomed_parents(self):
                return {}

        self._module.set_terminology_provider(StubProvider())

        source = {"code": "X1", "code_system": "CUSTOM-SYS"}
        target = {"code": {"coding": [{"code": "X1", "system": "urn:example:custom"}]}}
        self.assertEqual(check_system(source, target).status, "PASS")

        # A coding system the bundled provider knows about is no longer
        # resolved once a custom provider without that entry is installed.
        source_bundled = {"code": "X2", "code_system": "LN"}
        result = check_system(source_bundled, target)
        self.assertEqual(result.status, "INDETERMINATE")


class DocumentEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_documents((ROOT / "examples/document.hl7").read_text())

    def test_document_good(self):
        target = load_fhir_document_bundle(str(ROOT / "examples/document-bundle-good.json"))
        result = compare_many_documents(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.TYPE"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.AUTHOR"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.DATE"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.CONFIDENTIALITY"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.CONTENT_TYPE"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.SUPERSESSION"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].ATTACHMENT"], "PASS")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].PATIENT_REF"], "PASS")

    def test_document_mismatches_detected(self):
        target = load_fhir_document_bundle(str(ROOT / "examples/document-bundle-mismatch.json"))
        result = compare_many_documents(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.TYPE"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.AUTHOR"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.DATE"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.CONFIDENTIALITY"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.CONTENT_TYPE"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].DOCUMENT.SUPERSESSION"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].ATTACHMENT"], "FAIL")
        self.assertEqual(checks["DOCUMENT[DOC100-DOC].PATIENT_REF"], "FAIL")

    def test_document_missing_detected(self):
        target = load_fhir_document_bundle(str(ROOT / "examples/document-bundle-missing.json"))
        result = compare_many_documents(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(
            next(x for x in result["checks"] if x["rule_id"] == "DOCUMENT[DOC100-DOC].MISSING")["status"],
            "FAIL",
        )

    def test_parse_fhir_document_bundle_requires_document(self):
        with self.assertRaises(ValueError):
            load_fhir_document_bundle(str(ROOT / "examples/coverage-bundle-good.json"))


class MigrationBatchEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_resource_batch(str(ROOT / "examples/migration-source-batch.json"))

    def test_migration_good(self):
        target = load_fhir_resource_batch(str(ROOT / "examples/migration-target-batch-good.json"))
        result = compare_migration_batch(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RECORD[Condition/COND-1].LINEAGE"], "PASS")
        self.assertEqual(checks["RECORD[Condition/COND-2].LINEAGE"], "PASS")
        self.assertEqual(checks["RECORD[Procedure/PROC-1].LINEAGE"], "PASS")
        self.assertEqual(checks["CATEGORY[Patient].COUNT"], "PASS")
        self.assertEqual(checks["CATEGORY[Condition].COUNT"], "PASS")
        self.assertEqual(checks["CATEGORY[Procedure].COUNT"], "PASS")
        self.assertEqual(checks["RECORD[Condition/COND-1].MAPPING_BEHAVIOR"], "PASS")
        self.assertEqual(checks["RECORD[Provenance/PROV-1].PROVENANCE"], "PASS")
        self.assertEqual(checks["RECORD[Procedure/PROC-1].MAPPING_BEHAVIOR"], "PASS")

    def test_migration_mismatches_detected(self):
        target = load_fhir_resource_batch(str(ROOT / "examples/migration-target-batch-mismatch.json"))
        result = compare_migration_batch(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RECORD[Condition/COND-2].MISSING"], "FAIL")
        self.assertEqual(checks["RECORD[Condition/COND-1].LINEAGE"], "FAIL")
        self.assertEqual(checks["RECORD[Procedure/PROC-1].DUPLICATE"], "FAIL")
        self.assertEqual(checks["CATEGORY[Condition].COUNT"], "FAIL")
        self.assertEqual(checks["CATEGORY[Procedure].COUNT"], "FAIL")
        self.assertEqual(checks["CATEGORY[Patient].COUNT"], "PASS")
        self.assertEqual(checks["RECORD[Condition/COND-1].MAPPING_BEHAVIOR"], "FAIL")
        self.assertEqual(checks["RECORD[Provenance/PROV-1].PROVENANCE"], "FAIL")

    def test_parse_fhir_resource_batch_requires_bundle(self):
        with self.assertRaises(ValueError):
            load_fhir_resource_batch(str(ROOT / "examples/observation-good.json"))


class MigrationRunHistoryEngineTests(unittest.TestCase):
    @staticmethod
    def _report(statuses):
        return {"schema_version": "1.0", "overall": "PASS", "disclaimer": "",
                "checks": [{"rule_id": f"RULE[{i}]", "status": s, "source_value": "", "target_value": "",
                            "explanation": ""} for i, s in enumerate(statuses)]}

    def test_no_history_is_indeterminate(self):
        current = {"timestamp": "2024-01-02T00:00:00+00:00", "report": self._report(["PASS", "PASS"])}
        result = compare_migration_run_history([], current)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.SYNC_GAP"], "INDETERMINATE")
        self.assertEqual(checks["RUN.CONTRACT_COMPLIANCE"], "INDETERMINATE")
        self.assertEqual(checks["RUN.POPULATION_DISTRIBUTION"], "INDETERMINATE")

    def test_sync_gap_within_schedule_passes(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00", "report": self._report(["PASS"])}]
        current = {"timestamp": "2024-01-01T02:00:00+00:00", "report": self._report(["PASS"])}
        result = compare_migration_run_history(history, current, max_sync_gap_hours=24.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.SYNC_GAP"], "PASS")

    def test_sync_gap_exceeded_fails(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00", "report": self._report(["PASS"])}]
        current = {"timestamp": "2024-01-05T00:00:00+00:00", "report": self._report(["PASS"])}
        result = compare_migration_run_history(history, current, max_sync_gap_hours=24.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.SYNC_GAP"], "FAIL")

    def test_late_update_overwritten_detected(self):
        prior = {"schema_version": "1.0", "overall": "PASS", "disclaimer": "",
                 "checks": [{"rule_id": "RECORD[X].FIELD", "status": "PASS", "source_value": "", "target_value": "",
                             "explanation": ""}]}
        current_report = {"schema_version": "1.0", "overall": "FAIL", "disclaimer": "",
                           "checks": [{"rule_id": "RECORD[X].FIELD", "status": "FAIL", "source_value": "",
                                       "target_value": "", "explanation": ""}]}
        history = [{"timestamp": "2024-01-01T00:00:00+00:00", "report": prior}]
        current = {"timestamp": "2024-01-01T01:00:00+00:00", "report": current_report}
        result = compare_migration_run_history(history, current)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RECORD[X].FIELD.LATE_UPDATE_OVERWRITTEN"], "FAIL")

    def test_contract_compliance_degraded(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00",
                     "report": self._report(["PASS"] * 10)}]
        current = {"timestamp": "2024-01-02T00:00:00+00:00",
                   "report": self._report(["PASS"] * 5 + ["FAIL"] * 5)}
        result = compare_migration_run_history(history, current, max_compliance_drop_pct=10.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.CONTRACT_COMPLIANCE"], "FAIL")

    def test_population_distribution_shift_detected(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00",
                     "report": self._report(["PASS", "PASS", "PASS", "PASS"])}]
        current = {"timestamp": "2024-01-02T00:00:00+00:00",
                   "report": self._report(["INDETERMINATE", "INDETERMINATE", "INDETERMINATE", "PASS"])}
        result = compare_migration_run_history(history, current, max_population_shift_pct=20.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RULE[RULE[0]].POPULATION_DISTRIBUTION"], "FAIL")


class GenericRunHistoryEngineTests(unittest.TestCase):
    """compare_run_history() is domain-agnostic: it only reads the generic
    {"checks": [...]} report shape, so it must work the same way for a
    non-migration domain's report (here, a Claims report) as it does for
    migration-batch reports."""

    @staticmethod
    def _claims_report(statuses):
        return {"schema_version": "1.0", "overall": "PASS", "disclaimer": "",
                "checks": [{"rule_id": f"CLAIM[{i}].STATUS", "status": s, "source_value": "", "target_value": "",
                            "explanation": ""} for i, s in enumerate(statuses)]}

    def test_claims_run_history_detects_compliance_drop(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00",
                     "report": self._claims_report(["PASS"] * 10)}]
        current = {"timestamp": "2024-01-02T00:00:00+00:00",
                   "report": self._claims_report(["PASS"] * 4 + ["FAIL"] * 6)}
        result = compare_run_history(history, current, max_compliance_drop_pct=10.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.CONTRACT_COMPLIANCE"], "FAIL")

    def test_migration_alias_matches_generic_function(self):
        history = [{"timestamp": "2024-01-01T00:00:00+00:00",
                     "report": self._claims_report(["PASS"] * 10)}]
        current = {"timestamp": "2024-01-02T00:00:00+00:00",
                   "report": self._claims_report(["PASS"] * 10)}
        self.assertEqual(compare_migration_run_history(history, current),
                          compare_run_history(history, current))


class ExportRunHistoryEngineTests(unittest.TestCase):
    def test_no_history_is_indeterminate(self):
        result = compare_export_run_history([], {"timestamp": "2024-01-01T00:00:00+00:00"})
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.EXPORT_STALENESS"], "INDETERMINATE")

    def test_fresh_snapshot_passes(self):
        history = [{"timestamp": "2024-01-01T01:00:00+00:00"}]
        current = {"timestamp": "2024-01-01T00:00:00+00:00"}
        result = compare_export_run_history(history, current, max_staleness_hours=24.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.EXPORT_STALENESS"], "PASS")

    def test_stale_snapshot_fails(self):
        history = [{"timestamp": "2024-01-10T00:00:00+00:00"}]
        current = {"timestamp": "2024-01-01T00:00:00+00:00"}
        result = compare_export_run_history(history, current, max_staleness_hours=24.0)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["RUN.EXPORT_STALENESS"], "FAIL")


class CarePlanEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_careplan_bundle(str(ROOT / "examples/careplan-source-bundle.json"))

    def test_careplan_good(self):
        target = load_fhir_careplan_bundle(str(ROOT / "examples/careplan-target-bundle-good.json"))
        result = compare_many_careplans(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CAREPLAN[CAREPLAN-1].GOAL"], "PASS")
        self.assertEqual(checks["CAREPLAN[CAREPLAN-1].STATUS"], "PASS")

    def test_careplan_goal_omitted_and_status_changed(self):
        target = load_fhir_careplan_bundle(str(ROOT / "examples/careplan-target-bundle-mismatch.json"))
        result = compare_many_careplans(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CAREPLAN[CAREPLAN-1].GOAL"], "FAIL")
        self.assertEqual(checks["CAREPLAN[CAREPLAN-1].STATUS"], "FAIL")

    def test_parse_fhir_careplan_bundle_requires_careplan(self):
        with self.assertRaises(ValueError):
            load_fhir_careplan_bundle(str(ROOT / "examples/claim-bundle.json"))


class ServiceRequestEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_servicerequest_bundle(str(ROOT / "examples/servicerequest-source-bundle.json"))

    def test_servicerequest_good(self):
        target = load_fhir_servicerequest_bundle(str(ROOT / "examples/servicerequest-target-bundle-good.json"))
        result = compare_many_servicerequests(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["SERVICEREQUEST[SR-1].INTENT"], "PASS")
        self.assertEqual(checks["SERVICEREQUEST[SR-1].STATUS"], "PASS")

    def test_servicerequest_intent_changed(self):
        target = load_fhir_servicerequest_bundle(str(ROOT / "examples/servicerequest-target-bundle-mismatch.json"))
        result = compare_many_servicerequests(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["SERVICEREQUEST[SR-1].INTENT"], "FAIL")

    def test_parse_fhir_servicerequest_bundle_requires_servicerequest(self):
        with self.assertRaises(ValueError):
            load_fhir_servicerequest_bundle(str(ROOT / "examples/claim-bundle.json"))


class GoalEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_goal_bundle(str(ROOT / "examples/goal-source-bundle.json"))

    def test_goal_good(self):
        target = load_fhir_goal_bundle(str(ROOT / "examples/goal-target-bundle-good.json"))
        result = compare_many_goals(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["GOAL[GOAL-1].LIFECYCLE_STATUS"], "PASS")
        self.assertEqual(checks["GOAL[GOAL-1].ACHIEVEMENT_STATUS"], "PASS")

    def test_goal_mismatches_detected(self):
        target = load_fhir_goal_bundle(str(ROOT / "examples/goal-target-bundle-mismatch.json"))
        result = compare_many_goals(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["GOAL[GOAL-1].LIFECYCLE_STATUS"], "FAIL")
        self.assertEqual(checks["GOAL[GOAL-1].ACHIEVEMENT_STATUS"], "FAIL")

    def test_parse_fhir_goal_bundle_requires_goal(self):
        with self.assertRaises(ValueError):
            load_fhir_goal_bundle(str(ROOT / "examples/claim-bundle.json"))


class CareTeamEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_careteam_bundle(str(ROOT / "examples/careteam-source-bundle.json"))

    def test_careteam_good(self):
        target = load_fhir_careteam_bundle(str(ROOT / "examples/careteam-target-bundle-good.json"))
        result = compare_many_careteams(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CARETEAM[CARETEAM-1].STATUS"], "PASS")
        self.assertEqual(checks["CARETEAM[CARETEAM-1].PARTICIPANT"], "PASS")

    def test_careteam_mismatches_detected(self):
        target = load_fhir_careteam_bundle(str(ROOT / "examples/careteam-target-bundle-mismatch.json"))
        result = compare_many_careteams(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["CARETEAM[CARETEAM-1].STATUS"], "FAIL")
        self.assertEqual(checks["CARETEAM[CARETEAM-1].PARTICIPANT"], "FAIL")

    def test_parse_fhir_careteam_bundle_requires_careteam(self):
        with self.assertRaises(ValueError):
            load_fhir_careteam_bundle(str(ROOT / "examples/claim-bundle.json"))


class DetectedIssueEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_detectedissue_bundle(str(ROOT / "examples/detectedissue-source-bundle.json"))

    def test_detectedissue_good(self):
        target = load_fhir_detectedissue_bundle(str(ROOT / "examples/detectedissue-target-bundle-good.json"))
        result = compare_many_detected_issues(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DETECTEDISSUE[DI-1].STATUS"], "PASS")
        self.assertEqual(checks["DETECTEDISSUE[DI-1].EVIDENCE_DETAIL"], "PASS")

    def test_detectedissue_mismatches_detected(self):
        target = load_fhir_detectedissue_bundle(str(ROOT / "examples/detectedissue-target-bundle-mismatch.json"))
        result = compare_many_detected_issues(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DETECTEDISSUE[DI-1].STATUS"], "FAIL")
        self.assertEqual(checks["DETECTEDISSUE[DI-1].EVIDENCE_DETAIL"], "FAIL")

    def test_parse_fhir_detectedissue_bundle_requires_detectedissue(self):
        with self.assertRaises(ValueError):
            load_fhir_detectedissue_bundle(str(ROOT / "examples/claim-bundle.json"))


class TaskEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_task_bundle(str(ROOT / "examples/task-source-bundle.json"))

    def test_task_good(self):
        target = load_fhir_task_bundle(str(ROOT / "examples/task-target-bundle-good.json"))
        result = compare_many_tasks(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["TASK[TASK-1].STATUS"], "PASS")
        self.assertEqual(checks["TASK[TASK-1].BUSINESS_STATUS"], "PASS")

    def test_task_mismatches_detected(self):
        target = load_fhir_task_bundle(str(ROOT / "examples/task-target-bundle-mismatch.json"))
        result = compare_many_tasks(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["TASK[TASK-1].STATUS"], "FAIL")
        self.assertEqual(checks["TASK[TASK-1].BUSINESS_STATUS"], "FAIL")

    def test_parse_fhir_task_bundle_requires_task(self):
        with self.assertRaises(ValueError):
            load_fhir_task_bundle(str(ROOT / "examples/claim-bundle.json"))


class DiagnosticReportEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = parse_hl7_diagnosticreports((ROOT / "examples/diagnosticreport.hl7").read_text())

    def test_diagnosticreport_good(self):
        target = load_fhir_diagnosticreport_bundle(str(ROOT / "examples/diagnosticreport-bundle-good.json"))
        result = compare_many_diagnosticreports(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.CODE"], "PASS")
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.STATUS"], "PASS")
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.EFFECTIVE_DATE"], "PASS")
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.PERFORMER"], "PASS")

    def test_diagnosticreport_mismatches_detected(self):
        target = load_fhir_diagnosticreport_bundle(str(ROOT / "examples/diagnosticreport-bundle-mismatch.json"))
        result = compare_many_diagnosticreports(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.STATUS"], "FAIL")
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.EFFECTIVE_DATE"], "FAIL")
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.PERFORMER"], "FAIL")

    def test_diagnosticreport_performer_indeterminate_without_source(self):
        source = {"patient": self.source["patient"],
                  "diagnostic_reports": [dict(self.source["diagnostic_reports"][0], performer_id="")]}
        target = load_fhir_diagnosticreport_bundle(str(ROOT / "examples/diagnosticreport-bundle-good.json"))
        result = compare_many_diagnosticreports(source, target)
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["DIAGNOSTICREPORT[24323-8].DIAGNOSTICREPORT.PERFORMER"], "INDETERMINATE")

    def test_diagnosticreport_missing_detected(self):
        target = load_fhir_diagnosticreport_bundle(str(ROOT / "examples/diagnosticreport-bundle-missing.json"))
        result = compare_many_diagnosticreports(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        self.assertEqual(next(x for x in result["checks"] if x["rule_id"] == "DIAGNOSTICREPORT[24323-8].MISSING")["status"], "FAIL")

    def test_parse_hl7_diagnosticreports_requires_obr(self):
        with self.assertRaises(ValueError):
            parse_hl7_diagnosticreports("MSH|^~\\&|a|b|c|d|20260101||ORU^R01|1|P|2.5\nPID|1||X^^^T^MR")


class ProviderDirectoryEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_provider_directory_bundle(str(ROOT / "examples/provider-source-bundle.json"))

    def test_provider_directory_good(self):
        target = load_fhir_provider_directory_bundle(str(ROOT / "examples/provider-target-bundle-good.json"))
        result = compare_many_provider_directory(self.source, target)
        # Overall is INDETERMINATE rather than PASS because ROLE-1 and
        # ROLE-3 supply no PractitionerRole.period.end, so
        # PROVIDER.TERMINATION is INDETERMINATE for them (no FAIL is
        # present anywhere in the report).
        self.assertEqual(result["overall"], "INDETERMINATE")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NPI"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NETWORK_STATUS"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NEW_PATIENTS"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.SPECIALTY"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].LOCATION_ADDRESS"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].TELEHEALTH"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-1].PHONE"], "PASS")
        self.assertEqual(checks["PROVIDER[ROLE-2].PROVIDER.TERMINATION"], "PASS")
        self.assertEqual(checks["PLAN[plan-1].NETWORK_REF"], "PASS")
        self.assertNotIn("PRACTITIONER[pract-3].ORG_DUPLICATE", checks)

    def test_provider_directory_mismatches_detected(self):
        target = load_fhir_provider_directory_bundle(str(ROOT / "examples/provider-target-bundle-mismatch.json"))
        result = compare_many_provider_directory(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NPI"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NETWORK_STATUS"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.NEW_PATIENTS"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].PROVIDER.SPECIALTY"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].LOCATION_ADDRESS"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].TELEHEALTH"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-1].PHONE"], "FAIL")
        self.assertEqual(checks["PROVIDER[ROLE-2].PROVIDER.TERMINATION"], "FAIL")
        self.assertEqual(checks["PLAN[plan-1].NETWORK_REF"], "FAIL")
        self.assertEqual(checks["PRACTITIONER[pract-3].ORG_DUPLICATE"], "FAIL")

    def test_parse_fhir_provider_directory_bundle_requires_role(self):
        with self.assertRaises(ValueError):
            load_fhir_provider_directory_bundle(str(ROOT / "examples/claim-bundle.json"))


class MemberAttributionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_attribution_bundle(str(ROOT / "examples/attribution-source-bundle.json"))

    def test_attribution_good(self):
        target = load_fhir_attribution_bundle(str(ROOT / "examples/attribution-target-bundle-good.json"))
        result = compare_many_member_attribution(self.source, target)
        # MBR-2 has no source Coverage/Encounter resource, so those two
        # checks are INDETERMINATE (not PASS/FAIL), which makes the overall
        # verdict INDETERMINATE per evidence.report.overall_status().
        self.assertEqual(result["overall"], "INDETERMINATE")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["GROUP[attr-grp-1].CONTRACT_ID"], "PASS")
        self.assertEqual(checks["GROUP[attr-grp-1].RISK_ADJUSTMENT"], "PASS")
        self.assertEqual(checks["CATEGORY[Group].MEMBER_COUNT"], "PASS")
        self.assertEqual(checks["MEMBER[MBR-1].ATTRIBUTION_PERIOD"], "PASS")
        self.assertEqual(checks["MEMBER[MBR-1].COVERAGE_REF"], "PASS")
        self.assertEqual(checks["MEMBER[MBR-1].ENCOUNTER_HISTORY"], "PASS")
        self.assertEqual(checks["MEMBER[MBR-3].DECEASED"], "PASS")
        self.assertNotIn("MEMBER[MBR-1].DUAL_ATTRIBUTION", checks)
        self.assertNotIn("MEMBER[MBR-2].MISSING", checks)

    def test_attribution_mismatches_detected(self):
        target = load_fhir_attribution_bundle(str(ROOT / "examples/attribution-target-bundle-mismatch.json"))
        result = compare_many_member_attribution(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["GROUP[attr-grp-1].CONTRACT_ID"], "FAIL")
        self.assertEqual(checks["GROUP[attr-grp-1].RISK_ADJUSTMENT"], "FAIL")
        self.assertEqual(checks["CATEGORY[Group].MEMBER_COUNT"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-2].MISSING"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-1].DUAL_ATTRIBUTION"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-1].ATTRIBUTION_PERIOD"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-1].COVERAGE_REF"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-1].ENCOUNTER_HISTORY"], "FAIL")
        self.assertEqual(checks["MEMBER[MBR-3].DECEASED"], "FAIL")

    def test_parse_fhir_attribution_bundle_requires_group(self):
        with self.assertRaises(ValueError):
            load_fhir_attribution_bundle(str(ROOT / "examples/claim-bundle.json"))


class FormularyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_fhir_formulary_bundle(str(ROOT / "examples/formulary-source-bundle.json"))

    def test_formulary_good(self):
        target = load_fhir_formulary_bundle(str(ROOT / "examples/formulary-target-bundle-good.json"))
        result = compare_many_formulary(self.source, target)
        self.assertEqual(result["overall"], "PASS")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ITEM[FITEM-1].DRUG_TIER"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].COST_SHARE"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].PRIOR_AUTH"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].STEP_THERAPY"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].QUANTITY_LIMIT"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].PHARMACY_TYPE"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].RXNORM"], "PASS")
        self.assertEqual(checks["ITEM[FITEM-1].FORMULARY_LINK"], "PASS")
        self.assertEqual(checks["FORMULARY[formulary-1].EFFECTIVE_DATE"], "PASS")
        self.assertNotIn("ITEM[FITEM-2].MISSING", checks)

    def test_formulary_mismatches_detected(self):
        target = load_fhir_formulary_bundle(str(ROOT / "examples/formulary-target-bundle-mismatch.json"))
        result = compare_many_formulary(self.source, target)
        self.assertEqual(result["overall"], "FAIL")
        checks = {x["rule_id"]: x["status"] for x in result["checks"]}
        self.assertEqual(checks["ITEM[FITEM-1].DRUG_TIER"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].COST_SHARE"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].PRIOR_AUTH"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].STEP_THERAPY"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].QUANTITY_LIMIT"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].PHARMACY_TYPE"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].RXNORM"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-1].FORMULARY_LINK"], "FAIL")
        self.assertEqual(checks["ITEM[FITEM-2].MISSING"], "FAIL")

    def test_parse_fhir_formulary_bundle_requires_formulary_item(self):
        with self.assertRaises(ValueError):
            load_fhir_formulary_bundle(str(ROOT / "examples/claim-bundle.json"))


class AlertingTests(unittest.TestCase):
    """konkord.alerting.send_alert() must: (1) never send PHI-bearing check
    content, (2) stay a no-op unless a webhook URL is configured, and
    (3) only fire for alert-worthy statuses."""

    def setUp(self):
        from konkord import alerting

        self.alerting = alerting

    @staticmethod
    def _report(overall, statuses, correlation_id="corr-1", job_id="job-1"):
        return {
            "schema_version": "1.0", "overall": overall, "disclaimer": "",
            "correlation_id": correlation_id, "job_id": job_id, "created_at": "2024-01-01T00:00:00+00:00",
            "checks": [{"rule_id": f"RULE[{i}]", "status": s, "source_value": "SECRET-SOURCE",
                        "target_value": "SECRET-TARGET", "explanation": "explanation"}
                       for i, s in enumerate(statuses)],
        }

    def test_build_alert_payload_excludes_phi_fields(self):
        payload = self.alerting.build_alert_payload(self._report("FAIL", ["PASS", "FAIL"]))
        self.assertNotIn("checks", payload)
        dumped = json.dumps(payload)
        self.assertNotIn("SECRET-SOURCE", dumped)
        self.assertNotIn("SECRET-TARGET", dumped)
        self.assertEqual(payload["overall"], "FAIL")
        self.assertEqual(payload["counts"]["PASS"], 1)
        self.assertEqual(payload["counts"]["FAIL"], 1)
        self.assertEqual(payload["correlation_id"], "corr-1")
        self.assertEqual(payload["job_id"], "job-1")

    def test_send_alert_is_noop_without_webhook_url(self):
        with patch.object(self.alerting.urllib.request, "urlopen") as mock_urlopen:
            sent = self.alerting.send_alert(self._report("FAIL", ["FAIL"]), webhook_url=None)
        self.assertFalse(sent)
        mock_urlopen.assert_not_called()

    def test_send_alert_skips_pass_only_report_by_default(self):
        with patch.object(self.alerting.urllib.request, "urlopen") as mock_urlopen:
            sent = self.alerting.send_alert(self._report("PASS", ["PASS"]), webhook_url="http://example.invalid/hook")
        self.assertFalse(sent)
        mock_urlopen.assert_not_called()

    def test_send_alert_posts_for_fail_report(self):
        with patch.object(self.alerting.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = None
            sent = self.alerting.send_alert(self._report("FAIL", ["FAIL"]), webhook_url="http://example.invalid/hook")
        self.assertTrue(sent)
        mock_urlopen.assert_called_once()
        request_obj = mock_urlopen.call_args[0][0]
        self.assertEqual(request_obj.full_url, "http://example.invalid/hook")
        body = json.loads(request_obj.data.decode("utf-8"))
        self.assertNotIn("checks", body)

    def test_send_alert_swallows_network_errors(self):
        with patch.object(self.alerting.urllib.request, "urlopen", side_effect=OSError("boom")):
            sent = self.alerting.send_alert(self._report("FAIL", ["FAIL"]), webhook_url="http://example.invalid/hook")
        self.assertFalse(sent)


if __name__ == "__main__": unittest.main()
