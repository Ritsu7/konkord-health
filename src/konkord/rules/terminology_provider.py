"""Pluggable terminology data backend for `rules/terminology_observation.py`.

Scope: the terminology checks need small reference tables (coding-system
URIs, local-code mappings, approved ValueSet concepts, UCUM conversions,
deprecated-code replacements, SNOMED parent/child specificity) that differ
per deploying site and go stale over time. Rather than hardcoding them as
module-level dicts, this module defines a `TerminologyProvider` interface
so a site can supply its own data (e.g. exported from a real terminology
server or site mapping spreadsheet) without forking the rule logic.

Design intent:
- The rule functions in `terminology_observation.py` stay pure/deterministic
  `(source, target) -> RuleResult`; they just read through a provider
  instead of a hardcoded dict. Swapping providers never changes a check's
  logic, only the data it checks against.
- `BundledTerminologyProvider` preserves today's behavior exactly (same
  small demo/test tables), so this is a non-breaking refactor.
- `JSONTerminologyProvider` lets a site override/extend the bundled tables
  via a JSON file, selected with the `KONKORD_TERMINOLOGY_CONFIG`
  environment variable (same convention as `KONKORD_DATABASE_URL` /
  `KONKORD_API_KEYS`). Overrides are merged on top of the bundled defaults
  so a site only needs to specify what differs.
- This intentionally does NOT fetch anything over the network at request
  time: a reconciliation run must stay fast, offline-capable, and
  reproducible. Keeping terminology data current is a separate, offline
  concern (e.g. a periodic job that regenerates the JSON file from a real
  terminology source and is reviewed like any other change).
"""
from __future__ import annotations
import json
import os
from typing import Protocol


class TerminologyProvider(Protocol):
    """Read-only terminology data access used by the TERMINOLOGY.* rules."""

    def system_uri(self, coding_system: str) -> str | None: ...
    def canonical_code(self, local_code: str) -> str | None: ...
    def approved_codes(self, system: str) -> set[str] | None: ...
    def ucum_conversion(self, unit: str) -> tuple[str, float] | None: ...
    def deprecated_replacement(self, system: str, code: str) -> str | None: ...
    def snomed_parents(self) -> dict[str, set[str]]: ...


# Bundled defaults -- identical to the tables this module replaces, kept as
# the base every provider builds on (directly, or via JSON override).
_DEFAULT_SYSTEM_MAP = {
    "LN": "http://loinc.org",
    "SCT": "http://snomed.info/sct",
    "UCUM": "http://unitsofmeasure.org",
    "ICD10": "http://hl7.org/fhir/sid/icd-10-cm",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
}
_DEFAULT_LOCAL_CODE_MAP = {
    "HGBA1C": "4548-4",
    "17856-6": "4548-4",
    "GLUC": "2345-7",
    "NA": "2951-2",
}
_DEFAULT_APPROVED_VALUESET = {
    "http://loinc.org": {"4548-4", "2345-7", "2951-2", "17856-6"},
    "http://snomed.info/sct": {"17856-6", "444619008"},
}
_DEFAULT_UCUM_CONVERSION = {
    "mg/dL": ("mg/dL", 1.0),
    "mmol/L": ("mg/dL", 18.0),
    "g": ("mg", 1000.0),
    "mg": ("mg", 1.0),
    "%": ("%", 1.0),
}
_DEFAULT_DEPRECATED_CODES = {
    ("http://loinc.org", "2345-7"): "48643-1",
}
_DEFAULT_SNOMED_PARENT = {
    "444619008": {"17856-6"},
}


class BundledTerminologyProvider:
    """Default provider: Konkord's small, explicitly-scoped demo/test
    tables. Anything outside these tables is unknown -- callers treat that
    as INDETERMINATE rather than guessing (see terminology_observation.py)."""

    def system_uri(self, coding_system: str) -> str | None:
        return _DEFAULT_SYSTEM_MAP.get(coding_system)

    def canonical_code(self, local_code: str) -> str | None:
        return _DEFAULT_LOCAL_CODE_MAP.get(local_code)

    def approved_codes(self, system: str) -> set[str] | None:
        return _DEFAULT_APPROVED_VALUESET.get(system)

    def ucum_conversion(self, unit: str) -> tuple[str, float] | None:
        return _DEFAULT_UCUM_CONVERSION.get(unit)

    def deprecated_replacement(self, system: str, code: str) -> str | None:
        return _DEFAULT_DEPRECATED_CODES.get((system, code))

    def snomed_parents(self) -> dict[str, set[str]]:
        return _DEFAULT_SNOMED_PARENT


class JSONTerminologyProvider(BundledTerminologyProvider):
    """Loads a site's overrides from a JSON file, merged on top of the
    bundled defaults (a site only needs to specify what it wants to
    add/change). Expected JSON shape (all keys optional):

        {
          "system_map": {"LN": "http://loinc.org"},
          "local_code_map": {"HGBA1C": "4548-4"},
          "approved_valueset": {"http://loinc.org": ["4548-4"]},
          "ucum_conversion": {"mmol/L": ["mg/dL", 18.0]},
          "deprecated_codes": [["http://loinc.org", "2345-7", "48643-1"]],
          "snomed_parent": {"444619008": ["17856-6"]}
        }
    """

    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._system_map = {**_DEFAULT_SYSTEM_MAP, **data.get("system_map", {})}
        self._local_code_map = {**_DEFAULT_LOCAL_CODE_MAP, **data.get("local_code_map", {})}
        self._approved_valueset = {**_DEFAULT_APPROVED_VALUESET,
                                    **{k: set(v) for k, v in data.get("approved_valueset", {}).items()}}
        self._ucum_conversion = {**_DEFAULT_UCUM_CONVERSION,
                                  **{k: tuple(v) for k, v in data.get("ucum_conversion", {}).items()}}
        self._deprecated_codes = {**_DEFAULT_DEPRECATED_CODES,
                                   **{(s, c): r for s, c, r in data.get("deprecated_codes", [])}}
        self._snomed_parent = {**_DEFAULT_SNOMED_PARENT,
                                **{k: set(v) for k, v in data.get("snomed_parent", {}).items()}}

    def system_uri(self, coding_system: str) -> str | None:
        return self._system_map.get(coding_system)

    def canonical_code(self, local_code: str) -> str | None:
        return self._local_code_map.get(local_code)

    def approved_codes(self, system: str) -> set[str] | None:
        return self._approved_valueset.get(system)

    def ucum_conversion(self, unit: str) -> tuple[str, float] | None:
        return self._ucum_conversion.get(unit)

    def deprecated_replacement(self, system: str, code: str) -> str | None:
        return self._deprecated_codes.get((system, code))

    def snomed_parents(self) -> dict[str, set[str]]:
        return self._snomed_parent


_provider: TerminologyProvider | None = None


def get_terminology_provider() -> TerminologyProvider:
    """Lazily resolves the active provider: `KONKORD_TERMINOLOGY_CONFIG` (a
    JSON file path) if set, else the bundled defaults. Cached after first
    call; use `set_terminology_provider()`/`reset_terminology_provider()`
    to override (e.g. in tests, or an embedding application)."""
    global _provider
    if _provider is None:
        config_path = os.environ.get("KONKORD_TERMINOLOGY_CONFIG", "").strip()
        _provider = JSONTerminologyProvider(config_path) if config_path else BundledTerminologyProvider()
    return _provider


def set_terminology_provider(provider: TerminologyProvider) -> None:
    """Explicitly install a provider (e.g. a custom implementation backed
    by a real terminology server), bypassing env-var resolution."""
    global _provider
    _provider = provider


def reset_terminology_provider() -> None:
    """Test-only helper: clears the cached provider so the next
    `get_terminology_provider()` call re-resolves from the environment."""
    global _provider
    _provider = None
