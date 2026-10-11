"""HL7v2 ORU^R01 adapter.

Segment/field splitting is delegated to the `hl7` library (real HL7v2
grammar: encoding characters from MSH-2, component/repetition separators,
escape sequences), rather than naive `str.split("|")`. The higher-level
field-position extraction below (`_parse_*_fields`) still only supports the
specific segment layouts documented per function; this is a message
grammar parser, not a full HL7v2 conformance/profile validator.
"""
from __future__ import annotations
import hl7


def _segments(text: str) -> list:
    """Parse raw HL7v2 text into (segment_name, fields) pairs using the
    `hl7` library, where `fields[i]` is the raw string value of field `i`
    (fields[0] is the segment name itself, matching HL7 field numbering so
    existing position-based `_parse_*_fields` helpers work unchanged).

    Segment terminators `\\r`, `\\n`, and `\\r\\n` are all accepted (strict
    HL7v2 uses `\\r` only; real-world messages and files commonly use `\\n`).
    """
    normalized = text.replace("\r\n", "\r").replace("\n", "\r")
    try:
        message = hl7.parse(normalized)
    except Exception as exc:
        raise ValueError(f"Malformed HL7v2 message: {exc}") from exc
    return [(str(segment[0]), [str(segment[i]) for i in range(len(segment))]) for segment in message]


def _parse_obx_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    # OBX-3 is a CWE (Coded With Exceptions) data type: identifier^text^
    # name-of-coding-system^alternate-identifier^alternate-text^
    # name-of-alternate-coding-system^coding-system-version-id^...
    cwe = field(3).split("^")
    cwe_at = lambda i: cwe[i] if len(cwe) > i else ""
    # OBX-16 Responsible Observer (XCN) -- US Core "Must Support" mapped to
    # Observation.performer[]. OBX-17 Observation Method (CE) -- US Core
    # "Must Support" mapped to Observation.method.
    xcn = field(16).split("^")
    ce_method = field(17).split("^")
    return {
        "value_type": field(2),
        "code": cwe_at(0),
        "code_system": cwe_at(2),
        "display": cwe_at(1),
        "alt_code": cwe_at(3),
        "alt_text": cwe_at(4),
        "alt_system": cwe_at(5),
        "code_version": cwe_at(6),
        "value": field(5), "unit": field(6).split("^")[0],
        "reference_range": field(7), "interpretation": field(8),
        "status": field(11), "timestamp": field(14),
        "performer_id": xcn[0] if xcn else "",
        "method_code": ce_method[0] if ce_method else "",
    }


def _parse_pid_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    cx = field(3).split("^")
    xpn = field(5).split("^")
    return {
        "id": cx[0] if cx else "",
        "assigning_authority": cx[3] if len(cx) > 3 else "",
        "id_type": cx[4] if len(cx) > 4 else "",
        "family_name": xpn[0] if xpn else "",
        "given_name": xpn[1] if len(xpn) > 1 else "",
        "birth_date": field(7),
        "deceased_date": field(29),
        "deceased_indicator": field(30),
    }


def _parse_pv1_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    pl = field(3).split("^")
    xcn = field(7).split("^")
    return {
        "patient_class": field(2),
        "location": pl[0] if pl else "",
        "attending_id": xcn[0] if xcn else "",
        "visit_number": field(19).split("^")[0],
        "admit_datetime": field(44),
        "discharge_datetime": field(45),
    }


def _parse_obr_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    return {"specimen_type": field(15).split("^")[0]}


def parse_hl7_oru(text: str) -> dict:
    """Parse an ORU^R01-style message: one PID, zero or one PV1, zero or
    more OBR segments, and one or more OBX segments.

    Each OBX inherits the specimen type (OBR-15) of the most recent OBR
    segment preceding it, matching real ORU^R01 OBR/OBX grouping.

    Returns {"patient": dict | None, "encounter": dict | None,
    "observations": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    pv1_lines = [f for name, f in segments if name == "PV1"]
    if not any(name == "OBX" for name, _ in segments):
        raise ValueError("No OBX segments found")
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    if len(pv1_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PV1 segment; found {len(pv1_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None
    encounter = _parse_pv1_fields(pv1_lines[0]) if pv1_lines else None

    observations = []
    current_specimen_type = ""
    for name, fields in segments:
        if name == "OBR":
            current_specimen_type = _parse_obr_fields(fields)["specimen_type"]
        elif name == "OBX":
            obs = _parse_obx_fields(fields)
            obs["specimen_type"] = current_specimen_type
            observations.append(obs)
    return {"patient": patient, "encounter": encounter, "observations": observations}


def parse_hl7_oru_batch(text: str) -> list:
    """Parse a batched ORU^R01-style message containing multiple PID groups
    (one or more patients, each with its own PV1/OBR/OBX segments), as real
    lab-system interfaces commonly send.

    Unlike `parse_hl7_oru` (which enforces exactly one PID per message),
    this splits the message into per-patient groups at each PID segment and
    parses each group independently with the same OBR/OBX grouping rules.

    Returns a list of {"patient": dict, "encounter": dict | None,
    "observations": [dict, ...]}, one entry per PID segment encountered, in
    message order.
    """
    segments = _segments(text)
    if not any(name == "OBX" for name, _ in segments):
        raise ValueError("No OBX segments found")

    groups: list = []
    current: list = []
    for name, fields in segments:
        if name == "PID":
            if current:
                groups.append(current)
            current = [(name, fields)]
        elif current:
            current.append((name, fields))
    if current:
        groups.append(current)
    if not groups:
        raise ValueError("No PID segments found")

    results = []
    for group_segments in groups:
        pid_lines = [f for n, f in group_segments if n == "PID"]
        pv1_lines = [f for n, f in group_segments if n == "PV1"]
        patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None
        encounter = _parse_pv1_fields(pv1_lines[0]) if pv1_lines else None
        observations = []
        current_specimen_type = ""
        for n, fields in group_segments:
            if n == "OBR":
                current_specimen_type = _parse_obr_fields(fields)["specimen_type"]
            elif n == "OBX":
                obs = _parse_obx_fields(fields)
                obs["specimen_type"] = current_specimen_type
                observations.append(obs)
        results.append({"patient": patient, "encounter": encounter, "observations": observations})
    return results


def parse_hl7_obx(text: str) -> dict:
    """Backward-compatible single-observation parse (pre-0.2 API)."""
    parsed = parse_hl7_oru(text)
    if len(parsed["observations"]) != 1:
        raise ValueError(f"Prototype requires exactly one OBX segment; found {len(parsed['observations'])}")
    return parsed["observations"][0]


def _parse_rxe_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(2).split("^")
    cq = field(5).split("^")
    return {
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "code_system": ce[2] if len(ce) > 2 else "",
        "dose_amount": field(3),
        "dose_unit": cq[0] if cq else "",
        "frequency": field(1),
        "refills": field(12),
    }


def _parse_rxr_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(1).split("^")
    return {"route": ce[0] if ce else ""}


def _parse_orc_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    return {"order_control": field(1), "status": field(5), "date": field(9)}


def parse_hl7_rde(text: str) -> dict:
    """Parse an RDE^O11-style pharmacy/treatment encoded order message: one
    PID and one or more ORC/RXE(/RXR) order groups.

    This is a simplified field-position parser (not a full HL7v2 grammar
    parser), consistent in scope with `parse_hl7_oru`. Each order group is
    the ORC immediately preceding an RXE segment, plus an optional RXR
    segment anywhere after it (before the next ORC).

    Returns {"patient": dict | None, "medications": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    medications = []
    current_orc = None
    for name, fields in segments:
        if name == "ORC":
            current_orc = _parse_orc_fields(fields)
        elif name == "RXE":
            med = {**(current_orc or {}), **_parse_rxe_fields(fields), "route": ""}
            medications.append(med)
        elif name == "RXR" and medications:
            medications[-1]["route"] = _parse_rxr_fields(fields)["route"]
    if not medications:
        raise ValueError("No RXE segments found")
    return {"patient": patient, "medications": medications}


# HL7v2 Table 0128 (Allergy Severity, subset) -> FHIR AllergyIntolerance.reaction.severity.
_AL1_SEVERITY_MAP = {"SV": "severe", "MO": "moderate", "MI": "mild"}


def _parse_al1_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(3).split("^")
    reactions = [r for r in field(5).split("~") if r]
    return {
        "allergen_type": field(2),
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "code_system": ce[2] if len(ce) > 2 else "",
        "severity": field(4),
        "reactions": reactions,
        "identification_date": field(6),
        "clinical_status": "",
        "verification_status": "",
    }


def _parse_zal_fields(f: list) -> dict:
    """Parse a ZAL (site-defined Z-segment) carrying AllergyIntolerance
    clinical/verification status, since real HL7v2.5 AL1 has no such
    field. Z-segments are the standard HL7v2 mechanism for site-specific
    extensions; a trading-partner agreement that defines ZAL-1
    (clinical status) / ZAL-2 (verification status) is assumed here,
    analogous to how ROL carries procedure performer alongside PR1.

    Field positions: ZAL-1 clinical status (A=active, I=inactive,
    R=resolved), ZAL-2 verification status (U=unconfirmed, C=confirmed,
    F=refuted, E=entered-in-error).
    """
    field = lambda i: f[i] if len(f) > i else ""
    return {"clinical_status": field(1), "verification_status": field(2)}


def _parse_dg1_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(3).split("^")
    return {
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "code_system": ce[2] if len(ce) > 2 else "",
        "onset_date": field(5),
        "clinical_status": "",
        "verification_status": "",
    }


def _parse_zdg_fields(f: list) -> dict:
    """Parse a ZDG (site-defined Z-segment) carrying Condition
    clinical/verification status, since real HL7v2.5 DG1 has no such
    field. Same ZAL convention and rationale (see `_parse_zal_fields`),
    applied to diagnosis status instead of allergy status.
    """
    field = lambda i: f[i] if len(f) > i else ""
    return {"clinical_status": field(1), "verification_status": field(2)}


def parse_hl7_conditions(text: str) -> dict:
    """Parse a message containing one PID segment, zero or one PV1, and
    zero or more DG1 (diagnosis) segments, each optionally followed by a
    ZDG (site-defined) segment carrying clinical/verification status.

    Real HL7v2.5 DG1 has no clinical-status or verification-status field
    (no analog to FHIR Condition.clinicalStatus/verificationStatus); a
    following ZDG segment, if present, supplies ZDG-1 clinical status and
    ZDG-2 verification status (see `_parse_zdg_fields`). Diagnosis code
    (DG1-3) and onset/diagnosis date (DG1-5) always come from DG1 itself.

    Returns {"patient": dict | None, "encounter": dict | None, "conditions": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    pv1_lines = [f for name, f in segments if name == "PV1"]
    if len(pv1_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PV1 segment; found {len(pv1_lines)}")
    encounter = _parse_pv1_fields(pv1_lines[0]) if pv1_lines else None

    conditions = []
    for name, fields in segments:
        if name == "DG1":
            conditions.append(_parse_dg1_fields(fields))
        elif name == "ZDG" and conditions:
            zdg = _parse_zdg_fields(fields)
            conditions[-1]["clinical_status"] = zdg["clinical_status"]
            conditions[-1]["verification_status"] = zdg["verification_status"]
    if not conditions:
        raise ValueError("No DG1 segments found")
    return {"patient": patient, "encounter": encounter, "conditions": conditions}


def _parse_pr1_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(3).split("^")
    xcn = field(11).split("^")
    return {
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "code_system": ce[2] if len(ce) > 2 else "",
        "date": field(5),
        "surgeon_id": xcn[0] if xcn else "",
        "performer": "",
        "status": "",
    }


def _parse_rol_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    xcn = field(4).split("^")
    return {"performer": xcn[0] if xcn else ""}


def _parse_zpr_fields(f: list) -> dict:
    """Parse a ZPR (site-defined Z-segment) carrying Procedure.status,
    since real HL7v2.5 PR1 has no procedure-status field. Same ZAL/ZDG
    convention (see `_parse_zal_fields`); field position: ZPR-1 status
    (e.g. CM=completed, IP=in-progress, SP=stopped, PR=preparation).
    """
    field = lambda i: f[i] if len(f) > i else ""
    return {"status": field(1)}


def parse_hl7_procedures(text: str) -> dict:
    """Parse a message containing one PID segment and zero or more PR1
    (procedure) segments, each optionally followed by a ROL (role/performer)
    and/or ZPR (site-defined status) segment before the next PR1.

    Real HL7v2.5 PR1 has no procedure-status field (no analog to FHIR
    Procedure.status: preparation/in-progress/completed/stopped); a
    following ZPR segment, if present, supplies that status (see
    `_parse_zpr_fields`). Procedure code (PR1-3), date (PR1-5), and
    performer (PR1-11 Surgeon, overridden by a following ROL-4 if present)
    always come from PR1/ROL.

    Returns {"patient": dict | None, "procedures": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    procedures = []
    for name, fields in segments:
        if name == "PR1":
            procedures.append(_parse_pr1_fields(fields))
        elif name == "ROL" and procedures:
            performer = _parse_rol_fields(fields)["performer"]
            if performer:
                procedures[-1]["performer"] = performer
        elif name == "ZPR" and procedures:
            status = _parse_zpr_fields(fields)["status"]
            if status:
                procedures[-1]["status"] = status
    for proc in procedures:
        if not proc["performer"]:
            proc["performer"] = proc["surgeon_id"]
    if not procedures:
        raise ValueError("No PR1 segments found")
    return {"patient": patient, "procedures": procedures}


def parse_hl7_allergies(text: str) -> dict:
    """Parse a message containing one PID segment and zero or more AL1
    (patient allergy) segments, each optionally followed by a ZAL
    (site-defined) segment carrying clinical/verification status.

    Real HL7v2 AL1 has no clinical-status or verification-status field
    (no analog to FHIR AllergyIntolerance.clinicalStatus/verificationStatus);
    a following ZAL segment, if present, supplies ZAL-1 clinical status and
    ZAL-2 verification status (see `_parse_zal_fields`).

    Returns {"patient": dict | None, "allergies": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    allergies = []
    for name, fields in segments:
        if name == "AL1":
            allergies.append(_parse_al1_fields(fields))
        elif name == "ZAL" and allergies:
            zal = _parse_zal_fields(fields)
            allergies[-1]["clinical_status"] = zal["clinical_status"]
            allergies[-1]["verification_status"] = zal["verification_status"]
    if not allergies:
        raise ValueError("No AL1 segments found")
    return {"patient": patient, "allergies": allergies}


def _parse_in1_fields(f: list) -> dict:
    field = lambda i: f[i] if len(f) > i else ""
    payor_cx = field(3).split("^")
    relationship_ce = field(17).split("^")
    member_cx = field(49).split("^")
    return {
        "payor_id": payor_cx[0] if payor_cx else "",
        "payor_name": field(4),
        "group_number": field(8),
        "effective_date": field(12),
        "expiration_date": field(13),
        "relationship": relationship_ce[0] if relationship_ce else "",
        "cob_priority": field(22),
        "member_id": member_cx[0] if member_cx else "",
        "status": "",
    }


def _parse_zin_fields(f: list) -> dict:
    """Parse a ZIN (site-defined Z-segment) carrying Coverage.status,
    since real HL7v2.5 IN1 has no coverage-status field. Same ZAL/ZDG/ZPR
    convention (see `_parse_zal_fields`); field position: ZIN-1 status
    (e.g. AC=active, CA=cancelled, DR=draft, EE=entered-in-error).
    """
    field = lambda i: f[i] if len(f) > i else ""
    return {"status": field(1)}


def _parse_txa_fields(f: list) -> dict:
    """Parse a TXA (Transcription Document Header) segment, the HL7v2.5
    MDM^T02-family segment used for document-notification messages.

    Field positions per the HL7v2.5 TXA segment definition:
    TXA-2 Document Type (CWE), TXA-3 Document Content Presentation (ID,
    HL7 Table 0191), TXA-6 Origination Date/Time (DTM), TXA-9 Originator
    Code/Name (XCN), TXA-12 Unique Document Number (EI), TXA-13 Parent
    Document Number (EI), TXA-17 Document Completion Status (ID, HL7
    Table 0271), TXA-18 Document Confidentiality Status (ID, HL7 Table
    0272).
    """
    field = lambda i: f[i] if len(f) > i else ""
    cwe = field(2).split("^")
    xcn = field(9).split("^")
    return {
        "code": cwe[0] if cwe else "",
        "code_text": cwe[1] if len(cwe) > 1 else "",
        "content_presentation": field(3),
        "origination_date": field(6),
        "originator_id": xcn[0] if xcn else "",
        "originator_family_name": xcn[1] if len(xcn) > 1 else "",
        "document_id": field(12).split("^")[0],
        "parent_document_id": field(13).split("^")[0],
        "completion_status": field(17),
        "confidentiality_status": field(18),
    }


def parse_hl7_documents(text: str) -> dict:
    """Parse a message containing one PID segment and one or more TXA
    (transcription document header) segments.

    Real HL7v2.5 TXA has no field analogous to FHIR
    DocumentReference.content.attachment.hash (a content hash is computed
    over the document bytes, which TXA -- a metadata-only header without
    the document text -- never carries), so content-hash comparison
    (scenario-registry.csv SC-102) is out of scope here.

    Returns {"patient": dict | None, "documents": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    txa_lines = [f for name, f in segments if name == "TXA"]
    if not txa_lines:
        raise ValueError("No TXA segments found")
    documents = [_parse_txa_fields(f) for f in txa_lines]
    return {"patient": patient, "documents": documents}


def parse_hl7_coverage(text: str) -> dict:
    """Parse a message containing one PID segment and zero or more IN1
    (insurance) segments, each optionally followed by a ZIN (site-defined)
    segment carrying Coverage.status.

    Real HL7v2.5 IN1 has no coverage-status field (no analog to FHIR
    Coverage.status: active/cancelled/draft/entered-in-error); a following
    ZIN segment, if present, supplies that status (see
    `_parse_zin_fields`) -- same ZAL/ZDG/ZPR convention used for
    `parse_hl7_allergies`/`parse_hl7_conditions`/`parse_hl7_procedures`.

    Returns {"patient": dict | None, "coverages": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    coverages = []
    for name, fields in segments:
        if name == "IN1":
            coverages.append(_parse_in1_fields(fields))
        elif name == "ZIN" and coverages:
            status = _parse_zin_fields(fields)["status"]
            if status:
                coverages[-1]["status"] = status
    if not coverages:
        raise ValueError("No IN1 segments found")
    return {"patient": patient, "coverages": coverages}


def _parse_rxa_fields(f: list) -> dict:
    """Parse an HL7v2.5.1 RXA (pharmacy/treatment administration) segment
    for an immunization event, per the CDC/HL7 Immunization Implementation
    Guide profile of VXU^V04/RXA.

    RXA-3: date/time start of administration. RXA-5: administered code
    (CE, typically CVX). RXA-6/RXA-7: administered amount/units. RXA-15:
    lot number. RXA-16: expiration date. RXA-17: manufacturer (CE).
    RXA-20: completion status.
    """
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(5).split("^")
    manufacturer = field(17).split("^")
    return {
        "date": field(3),
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "code_system": ce[2] if len(ce) > 2 else "",
        "dose_amount": field(6),
        "dose_unit": field(7),
        "completion_status": field(20),
        "lot_number": field(15),
        "expiration_date": field(16),
        "manufacturer": manufacturer[1] if len(manufacturer) > 1 else manufacturer[0] if manufacturer else "",
    }


def _parse_obr_report_fields(f: list) -> dict:
    """Parse the OBR (Observation Request) segment fields relevant to the
    *report* itself (as opposed to `_parse_obr_fields`, which only pulls
    OBR-15 specimen type for OBX grouping), per the US Core Laboratory
    Result profile's mapping of OBR to FHIR DiagnosticReport.

    OBR-4: universal service identifier (CE, typically LOINC). OBR-7:
    observation date/time. OBR-25: result status (HL7 Table 0123: single
    character F/P/C/X, mapped to FHIR DiagnosticReport.status by the rule
    pack, not here). OBR-32: Principal Result Interpreter (CNN) -- US Core
    "Must Support" mapped to DiagnosticReport.performer.
    """
    field = lambda i: f[i] if len(f) > i else ""
    ce = field(4).split("^")
    cnn = field(32).split("^")
    return {
        "code": ce[0] if ce else "",
        "code_text": ce[1] if len(ce) > 1 else "",
        "date": field(7),
        "result_status": field(25),
        "performer_id": cnn[0] if cnn else "",
    }


def parse_hl7_diagnosticreports(text: str) -> dict:
    """Parse a message containing one PID segment and one or more OBR
    (observation request/report header) segments, for US Core Laboratory
    Result DiagnosticReport reconciliation.

    This is distinct from `parse_hl7_oru`/`parse_hl7_oru_batch`, which use
    OBR only to group OBX result segments by specimen type; this function
    instead extracts the OBR header fields that map onto
    DiagnosticReport.status/code/effectiveDateTime (OBR-25/4/7).

    Returns {"patient": dict | None, "diagnostic_reports": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    diagnostic_reports = [_parse_obr_report_fields(f) for name, f in segments if name == "OBR"]
    if not diagnostic_reports:
        raise ValueError("No OBR segments found")
    return {"patient": patient, "diagnostic_reports": diagnostic_reports}


def parse_hl7_immunizations(text: str) -> dict:
    """Parse a VXU^V04-style vaccination-update message: one PID segment
    and zero or more RXA (pharmacy/treatment administration) segments,
    each describing a single administered (or not-done) vaccine dose.

    Returns {"patient": dict | None, "immunizations": [dict, ...]}.
    """
    segments = _segments(text)
    pid_lines = [f for name, f in segments if name == "PID"]
    if len(pid_lines) > 1:
        raise ValueError(f"Prototype supports exactly one PID segment; found {len(pid_lines)}")
    patient = _parse_pid_fields(pid_lines[0]) if pid_lines else None

    immunizations = [_parse_rxa_fields(f) for name, f in segments if name == "RXA"]
    if not immunizations:
        raise ValueError("No RXA segments found")
    return {"patient": patient, "immunizations": immunizations}
