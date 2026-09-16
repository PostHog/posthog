"""Strict validation of a complete config version 2 candidate document.

Boundary: a complete canonical candidate (the document a writer is about to persist, with
server-assigned rule ids and seeds already resolved) plus explicit limits from the trusted
caller -> ``validate_config`` -> ``ValidatedConfig``, the evaluated fields the rule warning
detectors read, or ``ConfigValidationError`` carrying every field error in a fixed order
(root fields, then each rule's fields in rule order), so the same document always yields
the same list.
Nothing here reads or writes the database, assigns ids or seeds, checks permissions, or
mutates the input: a validated config says the document is well formed and admitted, not
that the caller may store it. The later trusted write path resolves request input into
the final document, calls this, runs ``rule_warnings.review_config`` and persists under
the existing row lock. No production caller exists yet.

Admitted family: person-assigned boolean flags with targeted_release and
percentage_rollout rules whose targeting uses person properties. Everything else the
published contract describes (string/number/object values, experiment rules, group
assignment, cohort/group/flag properties) is rejected with the ``unsupported`` code, so a
canonical fixture is never relabelled as malformed and no partially checked document is
accepted. Shape errors use the other codes. The canonical shape is the harness config
schema 1.0.0 in contract package 2.0.0; the semantic constraints (unique rule ids, two
decimal places, byte limits) come from its literal registry.
"""

import re
import json
import math
from collections.abc import Mapping
from dataclasses import field
from decimal import Decimal
from typing import Any, Literal, get_args

from posthog.hogql.property import parse_semver

from posthog.dataclasses import frozen
from posthog.models.property.property import STRING_PREFIX_SUFFIX_OPERATORS
from posthog.models.property.relative_date import determine_parsed_date_for_property_matching

from products.feature_flags.backend.facade.config import FlagReturnType, RuleType, detect_config_format

MAX_RULES = 100
MAX_PREDICATES_PER_RULE = 100
MAX_SEED_LENGTH = 400
MAX_PERCENTAGE_DECIMALS = 2

ConfigErrorCode = Literal["required", "invalid", "unknown_field", "not_unique", "unsupported", "limit_exceeded"]
RolloutMissPolicy = Literal["continue", "return_default"]
AdmittedRuleType = Literal["targeted_release", "percentage_rollout"]

ROLLOUT_MISS_POLICIES: tuple[RolloutMissPolicy, ...] = get_args(RolloutMissPolicy)
ASSIGNMENT_ALGORITHM = "sha1_60_v1"
PERSON_ASSIGNMENT = "person"
PROPERTY_TYPES: tuple[str, ...] = ("person", "cohort", "group", "flag")
# The contract's closed operator set. It has no aliases: a canonical document stores the
# operator the evaluator reads, so the v1 ``min``/``max`` spellings are invalid here.
PROPERTY_OPERATORS: frozenset[str] = frozenset(
    {
        "exact",
        "is_not",
        "icontains",
        "not_icontains",
        "icontains_multi",
        "not_icontains_multi",
        "regex",
        "not_regex",
        "gt",
        "gte",
        "lt",
        "lte",
        "semver_gt",
        "semver_gte",
        "semver_lt",
        "semver_lte",
        "semver_eq",
        "semver_neq",
        "semver_tilde",
        "semver_caret",
        "semver_wildcard",
        "is_set",
        "is_not_set",
        "is_date_exact",
        "is_date_after",
        "is_date_before",
        "in",
        "not_in",
        "flag_evaluates_to",
    }
    | set(STRING_PREFIX_SUFFIX_OPERATORS)
)
# Operator/value shapes mirror the v1 cross-field tier (filters_validation.py) so a property
# the v1 evaluator would reject is rejected here too. That module imports DRF and the v1
# serializer, which is why the table is repeated rather than imported.
_DATE_OPERATORS = frozenset({"is_date_exact", "is_date_after", "is_date_before"})
_STRING_VALUE_OPERATORS = frozenset({"regex", "not_regex", "icontains", "not_icontains"}) | set(
    STRING_PREFIX_SUFFIX_OPERATORS
)
_NUMERIC_COMPARISON_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
_LIST_VALUE_OPERATORS = frozenset({"icontains_multi", "not_icontains_multi"})
_SEMVER_OPERATORS = frozenset({op for op in PROPERTY_OPERATORS if op.startswith("semver_")})
_COHORT_ONLY_OPERATORS = frozenset({"in", "not_in"})
_FLAG_ONLY_OPERATORS = frozenset({"flag_evaluates_to"})

_ROOT_REQUIRED = ("version", "return_type", "default_value", "rules")
_ROOT_FIELDS = frozenset({*_ROOT_REQUIRED, "aggregation_group_type_index"})
# Final plan §5.1: v1-only top-level keys a v2 document must never carry.
_V1_ONLY_ROOT_FIELDS = frozenset(
    {
        "groups",
        "multivariate",
        "payloads",
        "super_groups",
        "holdout_groups",
        "holdout",
        "feature_enrollment",
        "early_exit",
        "bucketing_identifier",
    }
)
_COMMON_RULE_FIELDS = frozenset({"id", "rule_type", "targeting", "description", "metadata", "value"})
_ROLLOUT_RULE_FIELDS = frozenset({"rollout_percentage", "on_rollout_miss", "assignment_algorithm", "seed", "assign_by"})
_RULE_FIELDS: dict[str, frozenset[str]] = {
    "targeted_release": _COMMON_RULE_FIELDS,
    "percentage_rollout": _COMMON_RULE_FIELDS | _ROLLOUT_RULE_FIELDS,
}
_PROPERTY_FIELDS = frozenset(
    {"key", "value", "type", "operator", "group_type_index", "negation", "cohort_name", "group_key_names", "label"}
)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@frozen
class ConfigError:
    code: ConfigErrorCode
    # Presentation text. Never carries property values, seeds or metadata: the path in
    # ``attr`` identifies the field and the code identifies the problem.
    detail: str
    # Dotted path from the flag's ``filters`` field, e.g. ``filters.rules[2].seed``.
    attr: str


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[ConfigError]) -> None:
        super().__init__(f"{errors[0].attr}: {errors[0].detail}")
        self.errors = tuple(errors)


@frozen
class ValidationLimits:
    """Deployment limits the trusted caller supplies; the validator invents none.

    ``max_config_bytes`` is the per-flag filters limit the v1 write path already enforces
    (``settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES``). ``max_metadata_bytes`` bounds one
    rule's opaque ``metadata`` object; the contract requires a bound but no production
    value is decided yet, so it is required here rather than defaulted.
    """

    max_config_bytes: int
    max_metadata_bytes: int

    def __post_init__(self) -> None:
        for name in ("max_config_bytes", "max_metadata_bytes"):
            limit = getattr(self, name)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ValueError(f"{name} must be a positive integer")


@frozen
class Predicate:
    """One targeting property in the canonical form the detectors compare.

    Two rules whose predicate sets are equal target the same population; a rule whose set
    is a superset of another's targets a subset of it. The operator ``None`` reads as
    ``exact`` and the value is stored as canonical JSON text so the predicate is hashable.
    """

    key: str
    type: Literal["person"]
    operator: str
    value: str
    negation: bool


@frozen
class ValidatedRule:
    id: str
    rule_type: AdmittedRuleType
    predicates: frozenset[Predicate]
    value: bool
    rollout_percentage: Decimal | None = None
    on_rollout_miss: RolloutMissPolicy | None = None
    # Assignment seeds must not reach logs or tracebacks; the detectors only compare them.
    seed: str | None = field(default=None, repr=False)


@frozen
class ValidatedConfig:
    return_type: Literal["boolean"]
    default_value: bool | None
    rules: tuple[ValidatedRule, ...]  # stored order, which is evaluation order


def validate_config(document: object, *, limits: ValidationLimits) -> ValidatedConfig:
    """Validate a complete canonical candidate; raise ``ConfigValidationError`` otherwise.

    Deterministic, side-effect free and bounded by the byte limit, which is checked before
    anything else is read. The document is not modified.
    """
    errors: list[ConfigError] = []
    if not isinstance(document, Mapping):
        raise ConfigValidationError([ConfigError(code="invalid", detail="Must be an object.", attr="filters")])
    size = _encoded_size(document)
    if size is None:
        raise ConfigValidationError([ConfigError(code="invalid", detail="Must be a JSON document.", attr="filters")])
    if size > limits.max_config_bytes:
        raise ConfigValidationError(
            [ConfigError(code="limit_exceeded", detail="The configuration is too large.", attr="filters")]
        )

    if "version" not in document:
        errors.append(_required("filters.version"))
    elif detect_config_format(document).kind != "v2":
        errors.append(ConfigError(code="invalid", detail="Must be config version 2.", attr="filters.version"))
    for name in document:
        if name not in _ROOT_FIELDS:
            errors.append(_unknown_field(f"filters.{name}", v1_field=name in _V1_ONLY_ROOT_FIELDS))

    return_type = document.get("return_type")
    boolean_family = return_type == "boolean"
    if "return_type" not in document:
        errors.append(_required("filters.return_type"))
    elif return_type not in get_args(FlagReturnType):
        errors.append(
            ConfigError(code="invalid", detail="Must be boolean, string, number or object.", attr="filters.return_type")
        )
    elif not boolean_family:
        errors.append(
            ConfigError(
                code="unsupported",
                detail=f"Flags returning a {return_type} are not available yet. Only boolean is available.",
                attr="filters.return_type",
            )
        )

    if "default_value" not in document:
        errors.append(_required("filters.default_value"))
    elif boolean_family and not _is_bool_or_none(document["default_value"]):
        errors.append(ConfigError(code="invalid", detail="Must be true, false or null.", attr="filters.default_value"))

    if "aggregation_group_type_index" in document:
        index = document["aggregation_group_type_index"]
        if isinstance(index, bool) or not isinstance(index, int):
            errors.append(
                ConfigError(code="invalid", detail="Must be an integer.", attr="filters.aggregation_group_type_index")
            )
        else:
            errors.append(
                ConfigError(
                    code="unsupported",
                    detail="Group-assigned flags are not available yet.",
                    attr="filters.aggregation_group_type_index",
                )
            )

    rules: list[ValidatedRule] = []
    if "rules" not in document:
        errors.append(_required("filters.rules"))
    elif not isinstance(document["rules"], list):
        errors.append(ConfigError(code="invalid", detail="Must be an array.", attr="filters.rules"))
    elif len(document["rules"]) > MAX_RULES:
        errors.append(
            ConfigError(code="limit_exceeded", detail=f"At most {MAX_RULES} rules are allowed.", attr="filters.rules")
        )
    else:
        seen_ids: set[str] = set()
        for index, rule in enumerate(document["rules"]):
            validated = _validate_rule(rule, f"filters.rules[{index}]", boolean_family, limits, errors)
            if validated is None:
                continue
            if validated.id in seen_ids:
                errors.append(
                    ConfigError(code="not_unique", detail="Rule ids must be unique.", attr=f"filters.rules[{index}].id")
                )
            seen_ids.add(validated.id)
            rules.append(validated)

    if errors:
        raise ConfigValidationError(errors)
    return ValidatedConfig(return_type="boolean", default_value=document["default_value"], rules=tuple(rules))


def _validate_rule(
    rule: object, path: str, boolean_family: bool, limits: ValidationLimits, errors: list[ConfigError]
) -> ValidatedRule | None:
    if not isinstance(rule, Mapping):
        errors.append(ConfigError(code="invalid", detail="Must be an object.", attr=path))
        return None
    rule_type = rule.get("rule_type")
    if "rule_type" not in rule:
        errors.append(_required(f"{path}.rule_type"))
        return None
    if rule_type not in get_args(RuleType):
        errors.append(
            ConfigError(
                code="invalid",
                detail="Must be targeted_release, percentage_rollout or experiment.",
                attr=f"{path}.rule_type",
            )
        )
        return None
    if rule_type not in _RULE_FIELDS:
        errors.append(
            ConfigError(code="unsupported", detail="Experiment rules are not available yet.", attr=f"{path}.rule_type")
        )
        return None
    for name in rule:
        if name in _RULE_FIELDS[rule_type]:
            continue
        if name in _ROLLOUT_RULE_FIELDS:
            errors.append(
                ConfigError(
                    code="unknown_field",
                    detail="Only percentage_rollout rules have this field.",
                    attr=f"{path}.{name}",
                )
            )
        else:
            errors.append(_unknown_field(f"{path}.{name}"))

    before = len(errors)
    rule_id = rule.get("id")
    if "id" not in rule:
        errors.append(_required(f"{path}.id"))
    elif not isinstance(rule_id, str) or not _UUID.match(rule_id):
        errors.append(ConfigError(code="invalid", detail="Must be a UUID.", attr=f"{path}.id"))

    predicates = _validate_targeting(rule.get("targeting"), "targeting" in rule, f"{path}.targeting", errors)

    if "description" in rule and not isinstance(rule["description"], str):
        errors.append(ConfigError(code="invalid", detail="Must be a string.", attr=f"{path}.description"))
    if "metadata" in rule:
        _validate_metadata(rule["metadata"], f"{path}.metadata", limits, errors)

    value = rule.get("value")
    if boolean_family:
        if "value" not in rule:
            errors.append(_required(f"{path}.value"))
        elif not isinstance(value, bool):
            errors.append(ConfigError(code="invalid", detail="Must be true or false.", attr=f"{path}.value"))

    rollout: Decimal | None = None
    policy: RolloutMissPolicy | None = None
    seed: str | None = None
    if rule_type == "percentage_rollout":
        rollout = _validate_percentage(rule, f"{path}.rollout_percentage", errors)
        policy = _validate_literal(rule, "on_rollout_miss", ROLLOUT_MISS_POLICIES, path, errors)
        _validate_literal(rule, "assignment_algorithm", (ASSIGNMENT_ALGORITHM,), path, errors)
        seed = _validate_seed(rule, f"{path}.seed", errors)
        if "assign_by" in rule and rule["assign_by"] != PERSON_ASSIGNMENT:
            errors.append(ConfigError(code="invalid", detail="Must be person.", attr=f"{path}.assign_by"))

    if len(errors) > before or predicates is None or not boolean_family:
        return None
    assert isinstance(rule_id, str) and isinstance(value, bool)
    return ValidatedRule(
        id=rule_id,
        rule_type=rule_type,
        predicates=predicates,
        value=value,
        rollout_percentage=rollout,
        on_rollout_miss=policy,
        seed=seed,
    )


def _validate_targeting(
    targeting: object, present: bool, path: str, errors: list[ConfigError]
) -> frozenset[Predicate] | None:
    if not present:
        errors.append(_required(path))
        return None
    if not isinstance(targeting, Mapping):
        errors.append(ConfigError(code="invalid", detail="Must be an object.", attr=path))
        return None
    for name in targeting:
        if name != "properties":
            errors.append(_unknown_field(f"{path}.{name}"))
    if "properties" not in targeting:
        errors.append(_required(f"{path}.properties"))
        return None
    properties = targeting["properties"]
    if not isinstance(properties, list):
        errors.append(ConfigError(code="invalid", detail="Must be an array.", attr=f"{path}.properties"))
        return None
    if len(properties) > MAX_PREDICATES_PER_RULE:
        errors.append(
            ConfigError(
                code="limit_exceeded",
                detail=f"At most {MAX_PREDICATES_PER_RULE} properties are allowed per rule.",
                attr=f"{path}.properties",
            )
        )
        return None
    predicates = [
        _validate_property(prop, f"{path}.properties[{index}]", errors) for index, prop in enumerate(properties)
    ]
    if any(predicate is None for predicate in predicates):
        return None
    return frozenset(predicate for predicate in predicates if predicate is not None)


def _validate_property(prop: object, path: str, errors: list[ConfigError]) -> Predicate | None:
    if not isinstance(prop, Mapping):
        errors.append(ConfigError(code="invalid", detail="Must be an object.", attr=path))
        return None
    before = len(errors)
    for name in prop:
        if name not in _PROPERTY_FIELDS:
            errors.append(_unknown_field(f"{path}.{name}"))

    key = prop.get("key")
    if "key" not in prop:
        errors.append(_required(f"{path}.key"))
    elif not isinstance(key, str) or not key:
        errors.append(ConfigError(code="invalid", detail="Must be a non-empty string.", attr=f"{path}.key"))

    property_type = prop.get("type")
    if "type" not in prop:
        errors.append(_required(f"{path}.type"))
        return None
    if property_type not in PROPERTY_TYPES:
        errors.append(ConfigError(code="invalid", detail="Must be person, cohort, group or flag.", attr=f"{path}.type"))
        return None
    if property_type != "person":
        # Cohort and flag references need the dependency checks of the later dependency
        # validation task, and group properties need group assignment; none is admitted.
        # The checks below are person-property checks, so they must not run on these.
        errors.append(
            ConfigError(
                code="unsupported",
                detail=f"Targeting by {property_type} is not available yet. Only person properties are available.",
                attr=f"{path}.type",
            )
        )
        return None

    operator = prop.get("operator")
    if operator is None:
        operator = "exact"
    elif not isinstance(operator, str) or operator not in PROPERTY_OPERATORS:
        errors.append(ConfigError(code="invalid", detail="Unknown operator.", attr=f"{path}.operator"))
    elif operator in _COHORT_ONLY_OPERATORS:
        errors.append(
            ConfigError(code="invalid", detail="Only cohort properties use this operator.", attr=f"{path}.operator")
        )
    elif operator in _FLAG_ONLY_OPERATORS:
        errors.append(
            ConfigError(code="invalid", detail="Only flag properties use this operator.", attr=f"{path}.operator")
        )
    else:
        value_error = _property_value_error(operator, prop.get("value"))
        if value_error is not None:
            errors.append(ConfigError(code="invalid", detail=value_error, attr=f"{path}.value"))

    if prop.get("group_type_index") is not None:
        errors.append(
            ConfigError(
                code="invalid", detail="Only group properties have a group type index.", attr=f"{path}.group_type_index"
            )
        )
    negation = prop.get("negation")
    if not _is_bool_or_none(negation):
        errors.append(ConfigError(code="invalid", detail="Must be true, false or null.", attr=f"{path}.negation"))
    for name in ("cohort_name", "label"):
        if prop.get(name) is not None and not isinstance(prop[name], str):
            errors.append(ConfigError(code="invalid", detail="Must be a string or null.", attr=f"{path}.{name}"))
    group_key_names = prop.get("group_key_names")
    if group_key_names is not None and not (
        isinstance(group_key_names, Mapping) and all(isinstance(name, str) for name in group_key_names.values())
    ):
        errors.append(
            ConfigError(code="invalid", detail="Must be an object of strings or null.", attr=f"{path}.group_key_names")
        )

    if len(errors) > before:
        return None
    assert isinstance(key, str) and isinstance(operator, str)
    return Predicate(
        key=key,
        type="person",
        operator=operator,
        value=json.dumps(prop.get("value"), sort_keys=True, separators=(",", ":")),
        negation=bool(negation),
    )


def _property_value_error(operator: str, value: Any) -> str | None:
    if not _is_finite_json(value):
        return "Must be a finite number."
    if operator in _DATE_OPERATORS and determine_parsed_date_for_property_matching(value) is None:
        return "Must be a date."
    if operator in _STRING_VALUE_OPERATORS and not isinstance(value, str):
        return "Must be a string."
    if operator in _NUMERIC_COMPARISON_OPERATORS and not (isinstance(value, str) or _is_number(value)):
        return "Must be a number or a string."
    if operator in _LIST_VALUE_OPERATORS and not isinstance(value, list):
        return "Must be an array."
    if operator in _SEMVER_OPERATORS:
        if not isinstance(value, str):
            return "Must be a semver string."
        try:
            parse_semver(value.rstrip(".*") if operator == "semver_wildcard" else value)
        except (ValueError, IndexError):
            return "Must be a semver string."
    return None


def _validate_metadata(metadata: object, path: str, limits: ValidationLimits, errors: list[ConfigError]) -> None:
    if not isinstance(metadata, Mapping):
        errors.append(ConfigError(code="invalid", detail="Must be an object.", attr=path))
        return
    size = _encoded_size(metadata)
    if size is None or not _is_finite_json(metadata):
        errors.append(ConfigError(code="invalid", detail="Must be a JSON object.", attr=path))
    elif size > limits.max_metadata_bytes:
        errors.append(ConfigError(code="limit_exceeded", detail="The rule metadata is too large.", attr=path))


def _validate_percentage(rule: Mapping[str, Any], path: str, errors: list[ConfigError]) -> Decimal | None:
    if "rollout_percentage" not in rule:
        errors.append(_required(path))
        return None
    value = rule["rollout_percentage"]
    if not _is_number(value):
        errors.append(ConfigError(code="invalid", detail="Must be a finite number.", attr=path))
        return None
    if not 0 <= value <= 100:
        errors.append(ConfigError(code="invalid", detail="Must be between 0 and 100.", attr=path))
        return None
    # ``str`` gives the shortest decimal that round-trips the float, so 33.33 has two
    # places while a binary-float remainder test would call it inexact. Nothing is rounded.
    decimal_value = Decimal(str(value))
    exponent = decimal_value.normalize().as_tuple().exponent
    assert isinstance(exponent, int)  # finite values never carry the NaN/infinity markers
    if -exponent > MAX_PERCENTAGE_DECIMALS:
        errors.append(
            ConfigError(
                code="invalid", detail=f"Must have at most {MAX_PERCENTAGE_DECIMALS} decimal places.", attr=path
            )
        )
        return None
    return decimal_value


def _validate_literal(
    rule: Mapping[str, Any], name: str, allowed: tuple[str, ...], path: str, errors: list[ConfigError]
) -> Any:
    if name not in rule:
        errors.append(_required(f"{path}.{name}"))
        return None
    if rule[name] not in allowed:
        errors.append(ConfigError(code="invalid", detail=f"Must be {' or '.join(allowed)}.", attr=f"{path}.{name}"))
        return None
    return rule[name]


def _validate_seed(rule: Mapping[str, Any], path: str, errors: list[ConfigError]) -> str | None:
    if "seed" not in rule:
        errors.append(_required(path))
        return None
    seed = rule["seed"]
    if not isinstance(seed, str):
        errors.append(ConfigError(code="invalid", detail="Must be a string.", attr=path))
        return None
    if not 1 <= len(seed) <= MAX_SEED_LENGTH:
        errors.append(
            ConfigError(code="invalid", detail=f"Must be between 1 and {MAX_SEED_LENGTH} characters.", attr=path)
        )
        return None
    return seed


def _required(attr: str) -> ConfigError:
    return ConfigError(code="required", detail="This field is required.", attr=attr)


def _unknown_field(attr: str, *, v1_field: bool = False) -> ConfigError:
    detail = "Config version 1 fields are not allowed in a config version 2 document." if v1_field else "Unknown field."
    return ConfigError(code="unknown_field", detail=detail, attr=attr)


def _is_bool_or_none(value: object) -> bool:
    return value is None or isinstance(value, bool)


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _is_finite_json(value: object) -> bool:
    """Whether a JSON value carries no NaN or infinity; those are not RFC JSON and Postgres rejects them."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(_is_finite_json(child) for child in value.values())
    if isinstance(value, list | tuple):
        return all(_is_finite_json(child) for child in value)
    return True


def _encoded_size(value: object) -> int | None:
    """Encoded byte size with the same encoding as the v1 filter-size check, or None when the value is not JSON."""
    try:
        return len(json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return None
