from collections.abc import Mapping

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.edits import parse_percentage
from products.feature_flags.backend.facade.filters import condition_aggregation, condition_rollout_percentage
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@frozen
class ConditionShape:
    rollout: float | None
    has_properties: bool
    aggregation: int | None


@frozen
class FlagDescription:
    active: bool
    holdout: bool
    enrollment: bool
    multivariate: bool
    early_exit: bool
    evaluation_runtime: str | None
    conditions: tuple[ConditionShape, ...]
    variants: tuple[float | None, ...]


def _mappings(value: object) -> list[Mapping]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _group_index(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def describe_flag(flag: FeatureFlag) -> FlagDescription | None:
    if detect_config_format(flag.filters).kind != "v1":
        return None
    filters: Mapping = flag.filters or {}
    variants = _mappings((filters.get("multivariate") or {}).get("variants"))
    conditions = tuple(
        ConditionShape(
            rollout=parse_percentage(condition_rollout_percentage(condition)),
            has_properties=bool(condition.get("properties")),
            aggregation=_group_index(condition_aggregation(condition, filters.get("aggregation_group_type_index"))),
        )
        for condition in _mappings(filters.get("groups"))
    )
    return FlagDescription(
        active=bool(flag.active) and not flag.deleted and not flag.archived,
        holdout=bool(filters.get("holdout")),
        enrollment=bool(filters.get("feature_enrollment")),
        multivariate=bool(variants),
        early_exit=filters.get("early_exit") is True,
        evaluation_runtime=flag.evaluation_runtime if flag.evaluation_runtime in ("all", "client", "server") else None,
        conditions=conditions,
        variants=tuple(parse_percentage(variant.get("rollout_percentage")) for variant in variants),
    )
