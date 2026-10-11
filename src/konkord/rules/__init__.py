"""Rule registry and built-in rule packs.

Importing this package registers all built-in rule packs. New scenario
coverage is added by creating a new rule-pack module (e.g.
`konkord.rules.medication_observation`) and importing it here, or by
having a plugin register rules at startup -- the reconciliation engine
never needs to change.
"""
from .registry import register, rules_for_domain, all_rule_ids, RuleResult, Rule  # noqa: F401
from . import lab_observation  # noqa: F401  (registers LAB.* rules)
from . import identity_observation  # noqa: F401  (registers IDENTITY.* rules)
from . import encounter_observation  # noqa: F401  (registers ENCOUNTER.* rules)
from . import medication_observation  # noqa: F401  (registers MEDICATION.* rules)
from . import allergy_observation  # noqa: F401  (registers ALLERGY.* rules)
from . import condition_observation  # noqa: F401  (registers CONDITION.* rules)
from . import procedure_observation  # noqa: F401  (registers PROCEDURE.* rules)
from . import coverage_observation  # noqa: F401  (registers COVERAGE.* rules)
from . import priorauth_observation  # noqa: F401  (registers PRIORAUTH.* rules)
from . import claim_observation  # noqa: F401  (registers CLAIM.* rules)
from . import terminology_observation  # noqa: F401  (registers TERMINOLOGY.* rules)
from . import document_observation  # noqa: F401  (registers DOCUMENT.* rules)
from . import provider_observation  # noqa: F401  (registers PROVIDER.* rules)
from . import immunization_observation  # noqa: F401  (registers IMMUNIZATION.* rules)
from . import diagnosticreport_observation  # noqa: F401  (registers DIAGNOSTICREPORT.* rules)
