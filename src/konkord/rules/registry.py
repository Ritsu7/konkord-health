"""Deterministic, versioned rule registry.

This is the core extensibility point for the platform: new assurance
scenarios are added by registering a new `Rule` (here or in any rule-pack
module that imports this registry) without modifying the reconciliation
engine. Rules are pure functions: (source, target) -> RuleResult.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass(frozen=True)
class RuleResult:
    status: str  # PASS | WARN | FAIL | INDETERMINATE
    source_value: object = ""
    target_value: object = ""
    explanation: str = ""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    domain: str
    version: str
    check: Callable[[dict, dict], RuleResult]


_REGISTRY: Dict[str, Rule] = {}


def register(rule_id: str, domain: str = "observation", version: str = "1.0"):
    """Decorator to register a rule check function under a stable rule_id."""
    def deco(fn: Callable[[dict, dict], RuleResult]):
        if rule_id in _REGISTRY:
            raise ValueError(f"Rule '{rule_id}' is already registered")
        _REGISTRY[rule_id] = Rule(rule_id=rule_id, domain=domain, version=version, check=fn)
        return fn
    return deco


def rules_for_domain(domain: str) -> List[Rule]:
    return [r for r in _REGISTRY.values() if r.domain == domain]


def all_rule_ids() -> List[str]:
    return sorted(_REGISTRY)


def clear_registry_for_tests() -> None:
    """Test-only helper; not used by the engine itself."""
    _REGISTRY.clear()
