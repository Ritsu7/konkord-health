"""Rule pack: terminology/coding fidelity checks (HL7v2 OBX-3 CWE field ->
FHIR Observation.code CodeableConcept).

Scope: terminology concerns are cross-cutting rather than domain-specific,
but the only source structure Konkord parses that actually carries
coding-system/version/alternate-coding metadata is the HL7v2 CWE (Coded
With Exceptions) data type used in OBX-3:
    identifier^text^name-of-coding-system^alternate-identifier^
    alternate-text^name-of-alternate-coding-system^coding-system-version-id

These checks run under a dedicated "terminology" domain via
`reconciliation.compare_terminology()`, deliberately kept separate from
the "observation" domain's `compare()`/`compare_many()` so that adding
them cannot change the overall PASS/FAIL outcome of every existing
lab-result reconciliation.

Covers scenario-registry.csv SC-091 (code system changed), SC-092 (code
version mismatch), SC-096 (display contradicts code), and SC-099
(multi-coding incomplete).

SC-093, SC-094, SC-095, SC-097, and SC-098 are implemented against
reference data served by a `terminology_provider.TerminologyProvider`
(default: `BundledTerminologyProvider`, Konkord's small, explicitly
bundled demo/test tables; a site can instead supply its own data via
`KONKORD_TERMINOLOGY_CONFIG` or a custom provider -- see
`terminology_provider.py`). This is a deliberately narrow, deterministic
scope: only codes/units the active provider knows about are evaluated;
anything outside its data returns INDETERMINATE rather than guessing.

SC-100 (FHIR element meaning moved) is implemented as a concrete instance
of the structural-mapping defect class: the source's alternate/secondary
text (OBX-3.5) being mapped into the *primary* coding's display element
instead of the primary text (OBX-3.2) -- detectable because both source
fields are known and distinct, so a meaning-moved defect is
distinguishable from an ordinary display mismatch.

Like the other rule packs, checks are deterministic and never guess
terminology equivalence; insufficient evidence returns INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult
from .terminology_provider import get_terminology_provider

DOMAIN = "terminology"


def _codings(target: dict) -> list:
    return target.get("code", {}).get("coding", []) if target else []


def _primary_entry(target: dict, code: str) -> dict | None:
    for c in _codings(target):
        if c.get("code") == code:
            return c
    return None


@register("TERMINOLOGY.SYSTEM", domain=DOMAIN)
def check_system(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source code (OBX-3.1) supplied")
    expected = get_terminology_provider().system_uri(source.get("code_system", ""))
    if not expected:
        return RuleResult("INDETERMINATE",
                           explanation="Unsupported or missing source coding system (OBX-3.3); requires mapping contract")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Observation resource")
    entry = _primary_entry(target, source["code"])
    if entry is None:
        return RuleResult("FAIL", expected, "", "No target coding entry matches the source code")
    actual = entry.get("system", "")
    return RuleResult("PASS" if actual == expected else "FAIL", expected, actual,
                       "Coding system URI preservation (OBX-3.3 mapped to canonical URI vs "
                       "Observation.code.coding[].system)")


@register("TERMINOLOGY.VERSION", domain=DOMAIN)
def check_version(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code_version"):
        return RuleResult("INDETERMINATE", explanation="No source coding system version (OBX-3.7) supplied")
    if not target:
        return RuleResult("FAIL", source["code_version"], "", "Target has no Observation resource")
    entry = _primary_entry(target, source.get("code", ""))
    if entry is None:
        return RuleResult("FAIL", source["code_version"], "", "No target coding entry matches the source code")
    actual = entry.get("version", "")
    return RuleResult("PASS" if actual == source["code_version"] else "FAIL", source["code_version"], actual,
                       "Coding system version preservation (OBX-3.7 vs Observation.code.coding[].version)")


@register("TERMINOLOGY.DISPLAY", domain=DOMAIN)
def check_display(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("display"):
        return RuleResult("INDETERMINATE", explanation="No source display text (OBX-3.2) supplied")
    if not target:
        return RuleResult("FAIL", source["display"], "", "Target has no Observation resource")
    entry = _primary_entry(target, source.get("code", ""))
    if entry is None:
        return RuleResult("FAIL", source["display"], "", "No target coding entry matches the source code")
    actual = entry.get("display", "")
    if not actual:
        return RuleResult("INDETERMINATE",
                           explanation="Target coding entry has no display text to compare against")
    return RuleResult("PASS" if actual == source["display"] else "FAIL", source["display"], actual,
                       "Display text preservation (OBX-3.2 vs Observation.code.coding[].display)")


@register("TERMINOLOGY.MULTI_CODING", domain=DOMAIN)
def check_multi_coding(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("alt_code"):
        return RuleResult("INDETERMINATE", explanation="No source alternate coding (OBX-3.4/3.5/3.6) supplied")
    if not target:
        return RuleResult("FAIL", source["alt_code"], "", "Target has no Observation resource")
    codings = _codings(target)
    if len(codings) < 2:
        return RuleResult("FAIL", source["alt_code"], codings,
                           "Source provided an alternate coding, but target code.coding has fewer than 2 entries")
    actual = [c.get("code", "") for c in codings]
    match = source["alt_code"] in actual
    return RuleResult("PASS" if match else "FAIL", source["alt_code"], actual,
                       "Alternate coding preservation (OBX-3.4 vs a second entry in "
                       "Observation.code.coding[])")


@register("TERMINOLOGY.LOCAL_MAPPING", domain=DOMAIN)
def check_local_mapping(source: dict, target: dict) -> RuleResult:
    """SC-093: source's local/alternate code (OBX-3.4) must map to the
    expected canonical code per the bundled local-code mapping table, and
    the target's coding must carry that canonical code."""
    if not source or not source.get("alt_code"):
        return RuleResult("INDETERMINATE", explanation="No source local/alternate code (OBX-3.4) supplied")
    expected = get_terminology_provider().canonical_code(source["alt_code"])
    if expected is None:
        return RuleResult("INDETERMINATE",
                           explanation="Source local code not present in the bundled local-code mapping table")
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no Observation resource")
    entry = _primary_entry(target, expected)
    actual = entry.get("code", "") if entry else ""
    return RuleResult("PASS" if actual == expected else "FAIL", expected, actual,
                       "Local code mapping correctness (OBX-3.4 local code vs its bundled "
                       "canonical-code mapping, reflected in Observation.code.coding[].code)")


@register("TERMINOLOGY.VALUESET_BINDING", domain=DOMAIN)
def check_valueset_binding(source: dict, target: dict) -> RuleResult:
    """SC-094: target coding's code must be an approved concept for its
    coding system per the bundled ValueSet-binding table."""
    if not target:
        return RuleResult("FAIL", "", "", "Target has no Observation resource")
    entry = _primary_entry(target, source.get("code", "")) if source else None
    if entry is None:
        codings = _codings(target)
        entry = codings[0] if codings else None
    if entry is None:
        return RuleResult("INDETERMINATE", explanation="Target has no coding entry to evaluate")
    system, code = entry.get("system", ""), entry.get("code", "")
    approved = get_terminology_provider().approved_codes(system)
    if approved is None:
        return RuleResult("INDETERMINATE",
                           explanation="Target coding system not present in the bundled ValueSet-binding table")
    status = "PASS" if code in approved else "FAIL"
    return RuleResult(status, sorted(approved), code,
                       "Concept is bound to the approved ValueSet for its coding system "
                       "(bundled local ValueSet-binding table)")


@register("TERMINOLOGY.UCUM_CONVERSION", domain=DOMAIN)
def check_ucum_conversion(source: dict, target: dict) -> RuleResult:
    """SC-095: source value+unit must be numerically equivalent to target
    value+unit once converted to a common base unit via the bundled UCUM
    conversion table (e.g. mmol/L vs mg/dL)."""
    if not source or not source.get("value") or not source.get("unit"):
        return RuleResult("INDETERMINATE", explanation="No source value/unit (OBX-5/OBX-6) supplied")
    if not target:
        return RuleResult("FAIL", source["value"], "", "Target has no Observation resource")
    qty = target.get("valueQuantity") or {}
    target_value, target_unit = qty.get("value"), qty.get("code") or qty.get("unit")
    if target_value is None or not target_unit:
        return RuleResult("INDETERMINATE", explanation="Target has no valueQuantity to compare against")
    provider = get_terminology_provider()
    src_conv = provider.ucum_conversion(source["unit"])
    tgt_conv = provider.ucum_conversion(target_unit)
    if src_conv is None or tgt_conv is None or src_conv[0] != tgt_conv[0]:
        return RuleResult("INDETERMINATE",
                           explanation="One or both units are not in the bundled UCUM conversion table, "
                                       "or they don't share a common base unit")
    try:
        src_base = float(source["value"]) * src_conv[1]
        tgt_base = float(target_value) * tgt_conv[1]
    except (TypeError, ValueError):
        return RuleResult("INDETERMINATE", explanation="Source or target value is not numeric")
    match = abs(src_base - tgt_base) < 1e-6
    return RuleResult("PASS" if match else "FAIL", src_base, tgt_base,
                       "UCUM unit-conversion equivalence (OBX-5/OBX-6 converted to a common base "
                       "unit vs Observation.valueQuantity, via the bundled UCUM conversion table)")


@register("TERMINOLOGY.DEPRECATED_CODE", domain=DOMAIN)
def check_deprecated_code(source: dict, target: dict) -> RuleResult:
    """SC-097: target coding's code must not be a deprecated code per the
    bundled code-system currency/deprecation table."""
    if not target:
        return RuleResult("FAIL", "", "", "Target has no Observation resource")
    entry = _primary_entry(target, source.get("code", "")) if source else None
    if entry is None:
        codings = _codings(target)
        entry = codings[0] if codings else None
    if entry is None:
        return RuleResult("INDETERMINATE", explanation="Target has no coding entry to evaluate")
    system, code = entry.get("system", ""), entry.get("code", "")
    replacement = get_terminology_provider().deprecated_replacement(system, code)
    if replacement is None:
        return RuleResult("PASS", "current", code,
                           "Code is not present in the bundled deprecated-code table")
    return RuleResult("FAIL", replacement, code,
                       "Target uses a deprecated code per the bundled code-system currency table; "
                       f"expected replacement {replacement}")


@register("TERMINOLOGY.SNOMED_SPECIFICITY", domain=DOMAIN)
def check_snomed_specificity(source: dict, target: dict) -> RuleResult:
    """SC-098: target coding must not have been silently widened to a
    less-specific (parent) SNOMED code than the source's, per the bundled
    SNOMED parent/child specificity table."""
    snomed_code = source.get("alt_code") if source and source.get("alt_system") == "SCT" else (source or {}).get("code")
    if not snomed_code:
        return RuleResult("INDETERMINATE", explanation="No source SNOMED code (OBX-3.1 or alt coding) supplied")
    if not target:
        return RuleResult("FAIL", snomed_code, "", "Target has no Observation resource")
    codings = _codings(target)
    actual_codes = [c.get("code", "") for c in codings]
    for parent, children in get_terminology_provider().snomed_parents().items():
        if snomed_code in children:
            if parent in actual_codes:
                return RuleResult("FAIL", snomed_code, parent,
                                   "Target coding was widened to a less-specific parent SNOMED concept "
                                   "per the bundled SNOMED specificity table")
            if snomed_code in actual_codes:
                return RuleResult("PASS", snomed_code, snomed_code,
                                   "Target coding preserves source specificity per the bundled "
                                   "SNOMED specificity table")
    return RuleResult("INDETERMINATE",
                       explanation="Source code not present in the bundled SNOMED specificity table")


@register("TERMINOLOGY.ELEMENT_MEANING_MOVED", domain=DOMAIN)
def check_element_meaning_moved(source: dict, target: dict) -> RuleResult:
    """SC-100: the source's alternate/secondary text (OBX-3.5, meant to
    describe the alternate coding OBX-3.4) must not have been mapped into
    the *primary* coding's display instead of the primary text (OBX-3.2) --
    a structural-mapping defect where a field's meaning is relocated to a
    different element rather than simply dropped or wrong."""
    if not source or not source.get("display") or not source.get("alt_text"):
        return RuleResult("INDETERMINATE",
                           explanation="No source primary display (OBX-3.2) and alternate text (OBX-3.5) pair "
                                       "to distinguish a meaning-moved defect from a plain mismatch")
    if source["display"] == source["alt_text"]:
        return RuleResult("INDETERMINATE",
                           explanation="Source primary display and alternate text are identical; cannot "
                                       "distinguish correct mapping from a meaning-moved defect")
    if not target:
        return RuleResult("FAIL", source["display"], "", "Target has no Observation resource")
    entry = _primary_entry(target, source.get("code", ""))
    if entry is None:
        return RuleResult("FAIL", source["display"], "", "No target coding entry matches the source code")
    actual = entry.get("display", "")
    if actual == source["display"]:
        return RuleResult("PASS", source["display"], actual,
                           "Primary display text mapped to the correct structural element "
                           "(Observation.code.coding[].display)")
    if actual == source["alt_text"]:
        return RuleResult("FAIL", source["display"], actual,
                           "FHIR element meaning moved: the alternate text (OBX-3.5) was mapped into the "
                           "primary coding's display element instead of the primary text (OBX-3.2)")
    return RuleResult("INDETERMINATE",
                       explanation="Target display matches neither source field; not a meaning-moved defect")
