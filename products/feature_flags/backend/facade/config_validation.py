"""Strict validation of a complete config version 2 candidate document.

Boundary: a complete canonical candidate (the document a writer is about to persist, with
server-assigned rule ids and seeds already resolved) plus explicit limits from the trusted
caller -> ``validate_config`` -> ``ValidatedConfig``, the evaluated fields the rule warning
detectors read, or ``ConfigValidationError`` carrying every field error in a fixed order
(root fields, then each rule's fields in rule order), so the same document always yields
the same list. Nothing here reads or writes the database, assigns ids or seeds, checks
permissions, or mutates the input: a validated config says the document is well formed
and admitted, not that the caller may store it. The later trusted write path resolves
request input into the final document, calls ``rule_warnings.review_config`` (which
validates through this module and reports warnings) and persists under the existing row
lock. No production caller exists yet.

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
import sys
import json
from collections.abc import Callable, Mapping
from dataclasses import field
from decimal import Decimal
from typing import Any, Literal, get_args

from posthog.hogql.property import parse_semver

from posthog.dataclasses import frozen
from posthog.models.property.property import STRING_PREFIX_SUFFIX_OPERATORS
from posthog.models.property.relative_date import determine_parsed_date_for_property_matching

from products.feature_flags.backend.facade.config import FlagReturnType, RuleType, detect_config_format
from products.feature_flags.backend.types import PropertyFilterType

MAX_RULES = 100
MAX_PREDICATES_PER_RULE = 100
MAX_SEED_LENGTH = 400
MAX_PERCENTAGE_DECIMALS = 2

ConfigErrorCode = Literal["required", "invalid", "unknown_field", "not_unique", "unsupported", "limit_exceeded"]
RolloutMissPolicy = Literal["continue", "return_default"]
AdmittedRuleType = Literal["targeted_release", "percentage_rollout"]

RETURN_TYPES: tuple[str, ...] = get_args(FlagReturnType)
RULE_TYPES: tuple[str, ...] = get_args(RuleType)
ROLLOUT_MISS_POLICIES: tuple[RolloutMissPolicy, ...] = get_args(RolloutMissPolicy)
ASSIGNMENT_ALGORITHM = "sha1_60_v1"
PERSON_ASSIGNMENT = "person"
PROPERTY_TYPES: tuple[str, ...] = tuple(PropertyFilterType)
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
# the v1 evaluator would reject is rejected here too. That module is the v1 tier (it imports
# the v1 serializer), so the table is repeated rather than coupling this validator to it.
_DATE_OPERATORS = frozenset({"is_date_exact", "is_date_after", "is_date_before"})
_STRING_VALUE_OPERATORS = frozenset({"regex", "not_regex", "icontains", "not_icontains"}) | set(
    STRING_PREFIX_SUFFIX_OPERATORS
)
_NUMERIC_COMPARISON_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
_LIST_VALUE_OPERATORS = frozenset({"icontains_multi", "not_icontains_multi"})
_SEMVER_OPERATORS = frozenset({op for op in PROPERTY_OPERATORS if op.startswith("semver_")})
_NON_PERSON_OPERATORS = frozenset({"in", "not_in", "flag_evaluates_to"})

_ROOT_FIELDS = frozenset({"version", "return_type", "default_value", "rules", "aggregation_group_type_index"})
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
    """One person-property targeting condition in the canonical form the detectors compare.

    Two rules whose predicate sets are equal target the same population; a rule whose set
    is a superset of another's targets a subset of it. The operator ``None`` reads as
    ``exact`` and the value is stored as canonical JSON text so the predicate is hashable.
    """

    key: str
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
    """An admitted person-assigned boolean config; the family is fixed, so only the evaluated fields vary."""

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
        if name in _ROOT_FIELDS:
            continue
        v1_detail = "Config version 1 fields are not allowed in a config version 2 document."
        errors.append(_unknown_field(f"filters.{name}", v1_detail if name in _V1_ONLY_ROOT_FIELDS else None))

    return_type_ok = _field(document, "return_type", "filters", errors, _one_of(RETURN_TYPES))
    boolean_family = return_type_ok and document["return_type"] == "boolean"
    if return_type_ok and not boolean_family:
        errors.append(
            ConfigError(
                code="unsupported",
                detail=f"Flags returning a {document['return_type']} are not available yet. Only boolean is available.",
                attr="filters.return_type",
            )
        )
    if "default_value" not in document:
        errors.append(_required("filters.default_value"))
    elif boolean_family and not _is_bool_or_none(document["default_value"]):
        errors.append(ConfigError(code="invalid", detail="Must be true, false or null.", attr="filters.default_value"))
    if _field(document, "aggregation_group_type_index", "filters", errors, (_is_int, "Must be an integer."), False):
        errors.append(
            ConfigError(
                code="unsupported",
                detail="Group-assigned flags are not available yet.",
                attr="filters.aggregation_group_type_index",
            )
        )

    rules: list[ValidatedRule] = []
    if _field(document, "rules", "filters", errors, (lambda v: isinstance(v, list), "Must be an array.")):
        if len(document["rules"]) > MAX_RULES:
            errors.append(
                ConfigError(
                    code="limit_exceeded", detail=f"At most {MAX_RULES} rules are allowed.", attr="filters.rules"
                )
            )
        else:
            seen_ids: set[str] = set()
            for index, rule in enumerate(document["rules"]):
                validated = _validate_rule(rule, f"filters.rules[{index}]", boolean_family, limits, errors)
                if validated is None:
                    continue
                if validated.id in seen_ids:
                    errors.append(
                        ConfigError(
                            code="not_unique", detail="Rule ids must be unique.", attr=f"filters.rules[{index}].id"
                        )
                    )
                seen_ids.add(validated.id)
                rules.append(validated)

    if errors:
        raise ConfigValidationError(errors)
    return ValidatedConfig(default_value=document["default_value"], rules=tuple(rules))


def _validate_rule(
    rule: object, path: str, boolean_family: bool, limits: ValidationLimits, errors: list[ConfigError]
) -> ValidatedRule | None:
    if not isinstance(rule, Mapping):
        errors.append(ConfigError(code="invalid", detail="Must be an object.", attr=path))
        return None
    if not _field(rule, "rule_type", path, errors, _one_of(RULE_TYPES)):
        return None
    rule_type = rule["rule_type"]
    if rule_type not in _RULE_FIELDS:
        errors.append(
            ConfigError(code="unsupported", detail="Experiment rules are not available yet.", attr=f"{path}.rule_type")
        )
        return None
    for name in rule:
        if name not in _RULE_FIELDS[rule_type]:
            rollout_only = "Only percentage_rollout rules have this field."
            errors.append(_unknown_field(f"{path}.{name}", rollout_only if name in _ROLLOUT_RULE_FIELDS else None))

    before = len(errors)
    _field(rule, "id", path, errors, (lambda v: isinstance(v, str) and bool(_UUID.fullmatch(v)), "Must be a UUID."))
    predicates = _validate_targeting(rule, path, errors)
    _field(rule, "description", path, errors, (lambda v: isinstance(v, str), "Must be a string."), False)
    if "metadata" in rule:
        _validate_metadata(rule["metadata"], f"{path}.metadata", limits, errors)
    if boolean_family:
        _field(rule, "value", path, errors, (lambda v: isinstance(v, bool), "Must be true or false."))

    rollout: Decimal | None = None
    if rule_type == "percentage_rollout":
        rollout = _validate_percentage(rule, path, errors)
        _field(rule, "on_rollout_miss", path, errors, _one_of(ROLLOUT_MISS_POLICIES))
        _field(rule, "assignment_algorithm", path, errors, _one_of((ASSIGNMENT_ALGORITHM,)))
        seed_ok = (
            lambda v: isinstance(v, str) and 1 <= len(v) <= MAX_SEED_LENGTH,
            f"Must be between 1 and {MAX_SEED_LENGTH} characters.",
        )
        _field(rule, "seed", path, errors, seed_ok)
        _field(rule, "assign_by", path, errors, _one_of((PERSON_ASSIGNMENT,)), False)

    if len(errors) > before or predicates is None or not boolean_family:
        return None
    return ValidatedRule(
        id=rule["id"],
        rule_type=rule_type,
        predicates=predicates,
        value=rule["value"],
        rollout_percentage=rollout,
        on_rollout_miss=rule["on_rollout_miss"] if rollout is not None else None,
        seed=rule["seed"] if rollout is not None else None,
    )


def _validate_targeting(rule: Mapping[str, Any], path: str, errors: list[ConfigError]) -> frozenset[Predicate] | None:
    if not _field(rule, "targeting", path, errors, (lambda v: isinstance(v, Mapping), "Must be an object.")):
        return None
    targeting = rule["targeting"]
    path = f"{path}.targeting"
    for name in targeting:
        if name != "properties":
            errors.append(_unknown_field(f"{path}.{name}"))
    if not _field(targeting, "properties", path, errors, (lambda v: isinstance(v, list), "Must be an array.")):
        return None
    properties = targeting["properties"]
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
    _field(prop, "key", path, errors, (lambda v: isinstance(v, str) and bool(v), "Must be a non-empty string."))
    if not _field(prop, "type", path, errors, _one_of(PROPERTY_TYPES)):
        return None
    if prop["type"] != PropertyFilterType.PERSON:
        # Cohort and flag references need the dependency checks of the later dependency
        # validation task, and group properties need group assignment; none is admitted.
        # The checks below are person-property checks, so they must not run on these.
        errors.append(
            ConfigError(
                code="unsupported",
                detail=f"Targeting by {prop['type']} is not available yet. Only person properties are available.",
                attr=f"{path}.type",
            )
        )
        return None

    # The contract reads an omitted or null operator as ``exact``; its value is still checked.
    operator = prop.get("operator")
    if operator is None:
        operator = "exact"
    if not isinstance(operator, str) or operator not in PROPERTY_OPERATORS:
        errors.append(ConfigError(code="invalid", detail="Unknown operator.", attr=f"{path}.operator"))
    elif operator in _NON_PERSON_OPERATORS:
        errors.append(
            ConfigError(
                code="invalid", detail="Only cohort or flag properties use this operator.", attr=f"{path}.operator"
            )
        )
    else:
        value_error = _property_value_error(operator, prop.get("value"))
        if value_error is not None:
            errors.append(ConfigError(code="invalid", detail=value_error, attr=f"{path}.value"))

    no_group_index = (lambda v: v is None, "Only group properties have a group type index.")
    _field(prop, "group_type_index", path, errors, no_group_index, False)
    _field(prop, "negation", path, errors, (_is_bool_or_none, "Must be true, false or null."), False)
    for name in ("cohort_name", "label"):
        _field(
            prop, name, path, errors, (lambda v: v is None or isinstance(v, str), "Must be a string or null."), False
        )
    names_ok = (
        lambda v: v is None or (isinstance(v, Mapping) and all(isinstance(name, str) for name in v.values())),
        "Must be an object of strings or null.",
    )
    _field(prop, "group_key_names", path, errors, names_ok, False)

    if len(errors) > before:
        return None
    return Predicate(
        key=prop["key"],
        operator=operator,
        value=json.dumps(prop.get("value"), sort_keys=True, separators=(",", ":")),
        negation=bool(prop.get("negation")),
    )


def _property_value_error(operator: str, value: Any) -> str | None:
    if _encoded_size(value, allow_nan=False) is None:
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
    size = _encoded_size(metadata, allow_nan=False)
    if size is None:
        errors.append(ConfigError(code="invalid", detail="Must be a JSON object.", attr=path))
    elif size > limits.max_metadata_bytes:
        errors.append(ConfigError(code="limit_exceeded", detail="The rule metadata is too large.", attr=path))


def _validate_percentage(rule: Mapping[str, Any], path: str, errors: list[ConfigError]) -> Decimal | None:
    if not _field(rule, "rollout_percentage", path, errors, (_is_number, "Must be a finite number.")):
        return None
    value = rule["rollout_percentage"]
    path = f"{path}.rollout_percentage"
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


_Check = tuple[Callable[[Any], bool], str]  # (accepts the value?, detail when it does not)


def _field(
    obj: Mapping[str, Any], name: str, path: str, errors: list[ConfigError], check: _Check, required: bool = True
) -> bool:
    """Record ``required``/``invalid`` for ``obj[name]``; True when the field is present and passes the check."""
    if name not in obj:
        if required:
            errors.append(_required(f"{path}.{name}"))
        return False
    ok, detail = check
    if not ok(obj[name]):
        errors.append(ConfigError(code="invalid", detail=detail, attr=f"{path}.{name}"))
        return False
    return True


def _one_of(allowed: tuple[str, ...]) -> _Check:
    detail = f"Must be {', '.join(allowed[:-1])} or {allowed[-1]}." if len(allowed) > 1 else f"Must be {allowed[0]}."
    return (lambda v: v in allowed, detail)


def _required(attr: str) -> ConfigError:
    return ConfigError(code="required", detail="This field is required.", attr=attr)


def _unknown_field(attr: str, detail: str | None = None) -> ConfigError:
    return ConfigError(code="unknown_field", detail=detail or "Unknown field.", attr=attr)


def _is_bool_or_none(value: object) -> bool:
    return value is None or isinstance(value, bool)


def _is_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return -sys.float_info.max <= value <= sys.float_info.max


def _has_finite_numbers(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int | float):
        return _is_number(value)
    if isinstance(value, Mapping):
        return all(_has_finite_numbers(item) for item in value.values())
    if isinstance(value, list | tuple):
        return all(_has_finite_numbers(item) for item in value)
    return True


def _encoded_size(value: object, *, allow_nan: bool = True) -> int | None:
    """Encoded byte size with the same encoding as the v1 filter-size check, or None when the value is not JSON.

    With ``allow_nan=False``, numbers must fit the finite binary64 range used by the flag service.
    """
    try:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False, allow_nan=allow_nan)
        if not allow_nan and not _has_finite_numbers(value):
            return None
        return len(encoded.encode("utf-8"))
    except (TypeError, ValueError):
        return None
