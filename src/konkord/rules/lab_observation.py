"""Rule pack: numeric laboratory Observation preservation checks.

Each function registers one rule_id. Checks are deterministic and never
guess clinical equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from .registry import register, RuleResult


def dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _loinc_codes(target: dict) -> list:
    return [c.get("code", "") for c in target.get("code", {}).get("coding", []) if c.get("system") == "http://loinc.org"]


@register("LAB.CODE")
def check_code(source: dict, target: dict) -> RuleResult:
    if source["code_system"] != "LN":
        return RuleResult("INDETERMINATE", explanation="Unsupported source coding system; requires mapping contract")
    codes = _loinc_codes(target)
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes, "LOINC code preservation")


@register("LAB.VALUE")
def check_value(source: dict, target: dict) -> RuleResult:
    qty = target.get("valueQuantity", {})
    s_val, t_val = dec(source["value"]), dec(qty.get("value"))
    match = s_val is not None and t_val is not None and s_val == t_val
    return RuleResult("PASS" if match else "FAIL", source["value"], qty.get("value"), "Numeric result preservation")


@register("LAB.UNIT")
def check_unit(source: dict, target: dict) -> RuleResult:
    qty = target.get("valueQuantity", {})
    t_unit = qty.get("code") or qty.get("unit") or ""
    match = bool(source["unit"]) and source["unit"] == t_unit
    return RuleResult("PASS" if match else "FAIL", source["unit"], t_unit, "Unit preservation (literal comparison only)")


@register("LAB.STATUS")
def check_status(source: dict, target: dict) -> RuleResult:
    status_map = {"F": "final", "P": "preliminary", "C": "corrected"}
    if source["status"] not in status_map:
        return RuleResult("INDETERMINATE", explanation="Unsupported source status")
    expected = status_map[source["status"]]
    match = expected == target.get("status")
    return RuleResult("PASS" if match else "FAIL", expected, target.get("status", ""), "Result status preservation")


@register("LAB.INTERPRETATION")
def check_interpretation(source: dict, target: dict) -> RuleResult:
    interp = [c.get("code") for item in target.get("interpretation", []) for c in item.get("coding", [])]
    if not source["interpretation"]:
        return RuleResult("WARN", explanation="No source interpretation supplied")
    match = source["interpretation"] in interp
    return RuleResult("PASS" if match else "FAIL", source["interpretation"], interp, "Interpretation flag preservation")


_PLAIN_DECIMAL = re.compile(r"-?\d+(?:\.(\d+))?$")


def _decimal_places(value) -> int | None:
    """Count digits after the decimal point in a plain decimal string.

    Returns None if the value isn't a plain decimal (e.g. scientific
    notation, non-numeric text). Note: if the target was loaded from JSON
    via the standard parser, a trailing zero (e.g. "7.20") is lost before
    this check ever sees it (JSON has no distinct "7.20" vs "7.2" numeric
    literal once parsed to float) -- this rule can only catch precision
    changes that survive JSON number parsing (e.g. whole-number vs
    one-decimal, or differing non-zero decimal digit counts).
    """
    s = str(value).strip()
    m = _PLAIN_DECIMAL.fullmatch(s)
    if not m:
        return None
    return len(m.group(1)) if m.group(1) else 0


@register("LAB.PRECISION")
def check_precision(source: dict, target: dict) -> RuleResult:
    qty = target.get("valueQuantity", {})
    if "value" not in qty:
        return RuleResult("INDETERMINATE", explanation="Target has no numeric value to compare precision against")
    s_places = _decimal_places(source["value"])
    t_places = _decimal_places(qty.get("value"))
    if s_places is None or t_places is None:
        return RuleResult("INDETERMINATE", explanation="Source or target value is not a plain decimal; cannot assess precision")
    match = s_places == t_places
    return RuleResult(
        "PASS" if match else "FAIL",
        f"{s_places} decimal place(s)", f"{t_places} decimal place(s)",
        "Decimal precision preservation (limited by JSON float parsing; see rule docstring)",
    )


@register("LAB.VALUE_TYPE")
def check_value_type(source: dict, target: dict) -> RuleResult:
    vtype = source.get("value_type", "")
    if vtype not in ("NM", "SN"):
        return RuleResult("INDETERMINATE", explanation="Unsupported or missing source value type (OBX-2)")
    has_qty = "valueQuantity" in target
    if has_qty:
        return RuleResult("PASS", vtype, "valueQuantity", "Numeric result type preserved")
    if "valueString" in target:
        return RuleResult("FAIL", vtype, "valueString", "Numeric result unexpectedly converted to text")
    return RuleResult("FAIL", vtype, "(no value[x] present)", "Numeric result type not preserved")


@register("LAB.SPECIMEN")
def check_specimen(source: dict, target: dict) -> RuleResult:
    s_type = source.get("specimen_type", "")
    if not s_type:
        return RuleResult("INDETERMINATE", explanation="No source specimen type supplied (OBR-15)")
    t_type = target.get("specimen", {}).get("type", {}).get("text", "")
    match = t_type == s_type
    return RuleResult("PASS" if match else "FAIL", s_type, t_type, "Specimen type preservation (literal comparison only)")


@register("LAB.REFERENCE_RANGE")
def check_reference_range(source: dict, target: dict) -> RuleResult:
    rng = source["reference_range"]
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*", rng)
    if not m:
        return RuleResult("INDETERMINATE", explanation="Source range not in supported numeric interval format")
    rr = target.get("referenceRange", [])
    matches = any(
        dec(r.get("low", {}).get("value")) == dec(m.group(1)) and dec(r.get("high", {}).get("value")) == dec(m.group(2))
        for r in rr
    )
    return RuleResult("PASS" if matches else "FAIL", rng, rr, "Reference range preservation")


@register("LAB.METHOD")
def check_method(source: dict, target: dict) -> RuleResult:
    """OBX-17 (Observation Method, CE) vs Observation.method.coding[].code.

    US Core Laboratory Result Observation profile marks Observation.method
    as Must Support; dropping it during HL7v2-to-FHIR translation is a
    real, spec-relevant defect class, not a hypothetical.
    """
    method = source.get("method_code", "")
    if not method:
        return RuleResult("INDETERMINATE", explanation="No source observation method supplied (OBX-17)")
    codes = [c.get("code", "") for c in target.get("method", {}).get("coding", [])]
    match = method in codes
    return RuleResult("PASS" if match else "FAIL", method, codes, "Observation method preservation (OBX-17 vs Observation.method)")


@register("LAB.PERFORMER")
def check_performer(source: dict, target: dict) -> RuleResult:
    """OBX-16 (Responsible Observer, XCN) vs Observation.performer[].reference.

    US Core Laboratory Result Observation profile marks Observation.performer
    as Must Support; dropping it during HL7v2-to-FHIR translation is a real,
    spec-relevant defect class, not a hypothetical.
    """
    performer = source.get("performer_id", "")
    if not performer:
        return RuleResult("INDETERMINATE", explanation="No source responsible observer supplied (OBX-16)")
    refs = [p.get("reference", "") for p in target.get("performer", [])]
    match = any(performer in ref for ref in refs)
    return RuleResult("PASS" if match else "FAIL", performer, refs,
                       "Responsible observer preservation (OBX-16 vs Observation.performer[].reference, substring match)")
