"""Derive Konkord example fixtures (HL7 ORU + FHIR Bundle) from real
MITRE Synthea synthetic patient records (synthea-sample-data, FHIR R4).

Usage:
    python3 scripts/derive_synthea_fixtures.py <synthea_fhir_dir> <examples_dir>

This is a one-off / repeatable data-prep script (not part of the shipped
package); its output is committed to examples/. Source data comes from
https://github.com/synthetichealth/synthea-sample-data (synthetic-only,
no real patient data).
"""
from __future__ import annotations
import json
import sys

# Basic Metabolic Panel (8 components) + common CBC/lipid analytes, by LOINC
# code. Order here is the preference order used to fill the derived panel
# fixture (see PANEL_SIZE below) from whichever of these a given real
# Synthea patient record actually has recorded.
LOINC_PANEL = [
    "2345-7",   # Glucose [Mass/volume] in Serum or Plasma
    "3094-0",   # Urea nitrogen (BUN) [Mass/volume] in Serum or Plasma
    "2160-0",   # Creatinine [Mass/volume] in Serum or Plasma
    "2951-2",   # Sodium [Moles/volume] in Serum or Plasma
    "2823-3",   # Potassium [Moles/volume] in Serum or Plasma
    "2075-0",   # Chloride [Moles/volume] in Serum or Plasma
    "2028-9",   # Carbon dioxide, total [Moles/volume] in Serum or Plasma
    "17861-6",  # Calcium [Mass/volume] in Serum or Plasma
    "718-7",    # Hemoglobin [Mass/volume] in Blood
    "4544-3",   # Hematocrit [Volume Fraction] of Blood by Automated count
    "777-3",    # Platelets [#/volume] in Blood by Automated count
    "6690-2",   # Leukocytes [#/volume] in Blood by Automated count
    "2093-3",   # Cholesterol [Mass/volume] in Serum or Plasma
    "2085-9",   # Cholesterol in HDL [Mass/volume] in Serum or Plasma
    "18262-6",  # Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay
    "2571-8",   # Triglyceride [Mass/volume] in Serum or Plasma
    # Alternate specimen-type variants some Synthea records use instead of
    # the Serum/Plasma codes above.
    "6298-4",   # Potassium [Moles/volume] in Blood
    "2947-0",   # Sodium [Moles/volume] in Blood
    "2069-3",   # Chloride [Moles/volume] in Blood
    "20565-8",  # Carbon dioxide, total [Moles/volume] in Blood
    "49765-1",  # Calcium [Mass/volume] in Blood
    "2339-0",   # Glucose [Mass/volume] in Blood
    "38483-4",  # Creatinine [Mass/volume] in Blood
    "6299-2",   # Urea nitrogen [Mass/volume] in Blood
]
LAB_NAMES = {
    "2345-7": "Glucose", "2339-0": "Glucose",
    "3094-0": "Urea Nitrogen (BUN)", "6299-2": "Urea Nitrogen (BUN)",
    "2160-0": "Creatinine", "38483-4": "Creatinine",
    "2951-2": "Sodium", "2947-0": "Sodium",
    "2823-3": "Potassium", "6298-4": "Potassium",
    "2075-0": "Chloride", "2069-3": "Chloride",
    "2028-9": "Carbon Dioxide (CO2)", "20565-8": "Carbon Dioxide (CO2)",
    "17861-6": "Calcium", "49765-1": "Calcium",
    "718-7": "Hemoglobin",
    "4544-3": "Hematocrit",
    "777-3": "Platelets",
    "6690-2": "Leukocytes (WBC)",
    "2093-3": "Cholesterol, Total",
    "2085-9": "Cholesterol, HDL",
    "18262-6": "Cholesterol, LDL",
    "2571-8": "Triglycerides",
}
# Number of panel results to include in the derived HL7/FHIR panel fixture,
# taken in LOINC_PANEL preference order from whichever of those codes the
# chosen real Synthea patient actually has recorded.
PANEL_SIZE = 8
MSH_ENCODING_CHARS = "^~" + chr(92) + "&"


def pick_observations(bundle_path):
    data = json.load(open(bundle_path))
    entries = [e["resource"] for e in data.get("entry", [])]
    patient = next(r for r in entries if r["resourceType"] == "Patient")
    obs_by_code = {}
    for r in entries:
        if r.get("resourceType") != "Observation":
            continue
        codes = {c.get("code"): c for c in r.get("code", {}).get("coding", [])}
        for code in LOINC_PANEL:
            if code in codes and r.get("valueQuantity") and r.get("status") == "final":
                obs_by_code.setdefault(code, r)
    return patient, obs_by_code


def build_bundle(patient, obs_list, patient_id):
    pat = dict(patient)
    pat["id"] = patient_id
    entries = [{"resource": pat}]
    for obs in obs_list:
        o = dict(obs)
        o["subject"] = {"reference": "Patient/" + patient_id}
        # This fixture is a lab-only panel bundle with no Encounter resource;
        # drop the real Synthea encounter reference so ENCOUNTER.REFERENCE
        # doesn't fire on an encounter domain this fixture isn't exercising.
        o.pop("encounter", None)
        entries.append({"resource": o})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def _patient_mrn(patient: dict) -> str:
    for ident in patient.get("identifier", []):
        codes = [c.get("code") for c in ident.get("type", {}).get("coding", [])]
        if "MR" in codes:
            return ident.get("value", "")
    return ""


def _patient_mrn_system(patient: dict) -> str:
    for ident in patient.get("identifier", []):
        codes = [c.get("code") for c in ident.get("type", {}).get("coding", [])]
        if "MR" in codes:
            return ident.get("system", "")
    return ""


def _patient_name(patient: dict) -> tuple[str, str]:
    name = (patient.get("name") or [{}])[0]
    family = name.get("family", "")
    given = (name.get("given") or [""])[0]
    return family, given


def hl7_timestamp(fhir_dt):
    s = fhir_dt.replace("-", "").replace(":", "").replace("T", "")
    s = s.split("+")[0].split("Z")[0]
    return (s + "00000000")[:14]


def build_hl7(patient, obs_list, msg_id):
    mrn = _patient_mrn(patient)
    authority = _patient_mrn_system(patient)
    family, given = _patient_name(patient)
    lines = [
        "MSH|" + MSH_ENCODING_CHARS + "|LAB|HOSPITAL|APP|HOSPITAL|202610091000||ORU^R01|" + msg_id + "|P|2.5",
        "PID|1||" + mrn + "^^^" + authority + "^MR||" + family + "^" + given,
        "OBR|1||ORD-" + msg_id + "|24323-8^Metabolic Panel^LN",
    ]
    for i, obs in enumerate(obs_list, start=1):
        code = obs["code"]["coding"][0]["code"]
        name = LAB_NAMES.get(code, obs["code"].get("text", code))
        vq = obs["valueQuantity"]
        value = vq.get("value")
        unit = vq.get("unit") or vq.get("code") or ""
        rr = (obs.get("referenceRange") or [{}])[0]
        low = rr.get("low", {}).get("value", "")
        high = rr.get("high", {}).get("value", "")
        rr_str = (str(low) + "-" + str(high)) if low != "" and high != "" else ""
        interp_list = obs.get("interpretation") or [{}]
        interp = (interp_list[0].get("coding") or [{}])[0].get("code", "")
        ts = hl7_timestamp(obs.get("effectiveDateTime", ""))
        lines.append(
            "OBX|" + str(i) + "|NM|" + code + "^" + name + "^LN||" + str(value)
            + "|" + unit + "|" + rr_str + "|" + interp + "|||F|||" + ts
        )
    return "\n".join(lines) + "\n"


def build_bundle_bad_patient(patient, obs_list, patient_id, other_patient_id):
    """Bundle where the declared Patient is internally inconsistent: the
    first observation references a *different* patient than the bundle's
    declared Patient resource and the remaining observations. This matches
    the PATIENT.REFERENCE rule's actual check (internal subject-reference
    consistency within the target), not a cross-source identity mismatch.
    """
    pat = dict(patient)
    pat["id"] = patient_id
    entries = [{"resource": pat}]
    for i, obs in enumerate(obs_list):
        o = dict(obs)
        ref_id = other_patient_id if i == 0 else patient_id
        o["subject"] = {"reference": "Patient/" + ref_id}
        o.pop("encounter", None)
        entries.append({"resource": o})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def pick_medication(bundle_path):
    """Return (patient, MedicationRequest) for the first order in the file
    that has both a dose quantity and a timing frequency populated (most
    Synthea MedicationRequest entries only carry free-text dosage
    instructions, not structured dose/frequency).
    """
    data = json.load(open(bundle_path))
    entries = [e["resource"] for e in data.get("entry", [])]
    patient = next(r for r in entries if r["resourceType"] == "Patient")
    for r in entries:
        if r.get("resourceType") != "MedicationRequest":
            continue
        di = (r.get("dosageInstruction") or [{}])[0]
        dq = (di.get("doseAndRate") or [{}])[0].get("doseQuantity", {})
        freq = di.get("timing", {}).get("repeat", {})
        if dq.get("value") and freq.get("frequency"):
            return patient, r
    return patient, None


def pick_allergy(bundle_path):
    """Return (patient, AllergyIntolerance) for the first allergy in the
    file that has a reaction with a severity populated.
    """
    data = json.load(open(bundle_path))
    entries = [e["resource"] for e in data.get("entry", [])]
    patient = next(r for r in entries if r["resourceType"] == "Patient")
    for r in entries:
        if r.get("resourceType") != "AllergyIntolerance":
            continue
        reactions = r.get("reaction") or []
        if reactions and reactions[0].get("severity"):
            return patient, r
    return patient, None


# HL7v2 Table 0038 (Order Status, subset), FHIR MedicationRequest.status -> HL7.
_STATUS_TO_HL7 = {"active": "A", "completed": "CM", "cancelled": "CA", "stopped": "DC", "on-hold": "HD"}
# HL7v2 Table 0128 (Allergy Severity, subset), FHIR severity -> HL7.
_SEVERITY_TO_HL7 = {"severe": "SV", "moderate": "MO", "mild": "MI"}


def build_medication_bundle(patient, med, patient_id):
    pat = dict(patient)
    pat["id"] = patient_id
    m = dict(med)
    m["subject"] = {"reference": "Patient/" + patient_id}
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": pat}, {"resource": m}]}


def build_medication_hl7(med, msg_id):
    coding = med["medicationCodeableConcept"]["coding"][0]
    code, name = coding["code"], coding.get("display", coding["code"])
    di = med["dosageInstruction"][0]
    dose_qty = di["doseAndRate"][0]["doseQuantity"]
    dose_amount, dose_unit = dose_qty.get("value", ""), dose_qty.get("unit", "")
    repeat = di["timing"]["repeat"]
    period, period_unit = repeat.get("period", ""), repeat.get("periodUnit", "")
    frequency = f"{repeat['frequency']}/{period}{period_unit}" if period else str(repeat["frequency"])
    status = _STATUS_TO_HL7.get(med.get("status", ""), "")
    order_date = hl7_timestamp(med.get("authoredOn", ""))
    lines = [
        "MSH|" + MSH_ENCODING_CHARS + "|PHARMACY|HOSPITAL|APP|HOSPITAL|202610091000||RDE^O11|" + msg_id + "|P|2.5",
        "PID|1||SYNTHEA-MED-A^^^TEST^MR||Synthea^Patient",
        "ORC|RE||||" + status + "||||" + order_date,
        "RXE|" + frequency + "|" + code + "^" + name + "^RXNORM|" + str(dose_amount) + "||" + dose_unit + "^^",
    ]
    return "\n".join(lines) + "\n"


def build_allergy_bundle(patient, allergy, patient_id):
    pat = dict(patient)
    pat["id"] = patient_id
    a = dict(allergy)
    a["patient"] = {"reference": "Patient/" + patient_id}
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": pat}, {"resource": a}]}


def build_allergy_hl7(allergy, msg_id):
    coding = allergy["code"]["coding"][0]
    code, name = coding["code"], coding.get("display", coding["code"])
    reaction = allergy["reaction"][0]
    severity = _SEVERITY_TO_HL7.get(reaction.get("severity", ""), "")
    manifestations = []
    for m in reaction.get("manifestation", []):
        text = m.get("text") or (m.get("coding") or [{}])[0].get("display", "")
        if text:
            manifestations.append(text)
    allergen_type = "DA" if "medication" in (allergy.get("category") or []) else "EA"
    id_date = hl7_timestamp(allergy.get("recordedDate", ""))[:8]
    lines = [
        "MSH|" + MSH_ENCODING_CHARS + "|REG|HOSPITAL|APP|HOSPITAL|202610091000||ADT^A04|" + msg_id + "|P|2.5",
        "PID|1||SYNTHEA-ALLERGY-A^^^TEST^MR||Synthea^Patient",
        "AL1|1|" + allergen_type + "|" + code + "^" + name + "^SCT|" + severity + "|" + "~".join(manifestations) + "|" + id_date,
    ]
    return "\n".join(lines) + "\n"


def main():
    src_dir, out_examples = sys.argv[1], sys.argv[2]
    file_a = "Benito209_Gulgowski816_8d91c36a-1f7e-3842-9f14-8d567ed9cdcd.json"
    file_b = "Boyce638_Nolan344_9c5b16dc-8a47-896c-4d74-f96f8c98891b.json"

    pa, obs_a = pick_observations(src_dir + "/" + file_a)
    pb, _obs_b = pick_observations(src_dir + "/" + file_b)

    obs_a_list = [obs_a[c] for c in LOINC_PANEL if c in obs_a][:PANEL_SIZE]

    bundle_good = build_bundle(pa, obs_a_list, "synthea-pat-a")
    hl7_good = build_hl7(pa, obs_a_list, "MSG-SYNTHEA-A")
    bundle_missing = build_bundle(pa, obs_a_list[:1], "synthea-pat-a")
    bundle_duplicate = build_bundle(pa, obs_a_list + [obs_a_list[0]], "synthea-pat-a")
    bundle_bad_patient = build_bundle_bad_patient(pa, obs_a_list, "synthea-pat-a", "synthea-pat-b-other")

    out = {
        "panel-synthea.hl7": hl7_good,
        "panel-synthea-bundle-good.json": json.dumps(bundle_good, indent=2),
        "panel-synthea-bundle-missing.json": json.dumps(bundle_missing, indent=2),
        "panel-synthea-bundle-duplicate.json": json.dumps(bundle_duplicate, indent=2),
        "panel-synthea-bundle-bad-patient.json": json.dumps(bundle_bad_patient, indent=2),
    }

    # Medication: a real Synthea patient record with a MedicationRequest
    # that has structured dose amount/unit and timing frequency.
    med_file = "Martha161_Wiegand701_babc4b97-d859-0fe4-2874-fb6fe493ae6b.json"
    pmed, med = pick_medication(src_dir + "/" + med_file)
    if med is not None:
        out["medication-synthea.hl7"] = build_medication_hl7(med, "MSG-SYNTHEA-MED-A")
        out["medication-synthea-bundle-good.json"] = json.dumps(
            build_medication_bundle(pmed, med, "synthea-med-a"), indent=2
        )

    # Allergy: a real Synthea patient record with an AllergyIntolerance
    # reaction that has a severity populated.
    allergy_file = "Danial835_Grimes165_765bd034-e8d7-f102-eb1c-4b7792fc5684.json"
    pal, allergy = pick_allergy(src_dir + "/" + allergy_file)
    if allergy is not None:
        out["allergy-synthea.hl7"] = build_allergy_hl7(allergy, "MSG-SYNTHEA-ALLERGY-A")
        out["allergy-synthea-bundle-good.json"] = json.dumps(
            build_allergy_bundle(pal, allergy, "synthea-allergy-a"), indent=2
        )

    for name, content in out.items():
        with open(out_examples + "/" + name, "w") as f:
            f.write(content)
    print("wrote:", list(out.keys()))


if __name__ == "__main__":
    main()
