from datetime import datetime
from uuid import UUID

from django.db import IntegrityError

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.scoring_lab import ScoringPreviewRow, preview_scoring_formula
from products.growth.backend.enrichment.scoring_rules import parse_scoring_rules
from products.growth.backend.models import IcpScoringConfig


class ScoringConfigNotFound(ValueError):
    pass


class ScoringPreviewUnavailable(ValueError):
    pass


class DuplicateScoringVersion(ValueError):
    pass


@frozen
class ScoringConfig:
    id: UUID
    version: str
    source: str
    is_active: bool
    created_at: datetime
    created_by_email: str | None


def _config_result(config: IcpScoringConfig) -> ScoringConfig:
    return ScoringConfig(
        id=config.id,
        version=config.version,
        source=parse_scoring_rules(config.scoring_rules).source,
        is_active=config.is_active,
        created_at=config.created_at,
        created_by_email=config.created_by.email if config.created_by else None,
    )


def _get_config(config_id: UUID) -> IcpScoringConfig:
    try:
        return IcpScoringConfig.objects.select_related("created_by").get(pk=config_id)
    except IcpScoringConfig.DoesNotExist as error:
        raise ScoringConfigNotFound("Scoring configuration does not exist.") from error


def default_scoring_source() -> str:
    return parse_scoring_rules({}).source


def validate_scoring_source(source: str) -> None:
    parse_scoring_rules({"source": source})


def list_scoring_configs() -> list[ScoringConfig]:
    configs = IcpScoringConfig.objects.select_related("created_by").order_by("-created_at")[:100]
    return [_config_result(config) for config in configs]


def preview_formula(source: str, base_config_id: UUID, sample: int) -> list[ScoringPreviewRow]:
    active = IcpScoringConfig.objects.filter(is_active=True).first()
    if active is None:
        raise ScoringPreviewUnavailable("Import and activate the initial scoring lists before previewing a formula.")
    return preview_scoring_formula(active, _get_config(base_config_id), source, sample)


def save_scoring_formula(source: str, version: str, base_config_id: UUID, created_by_id: int) -> ScoringConfig:
    base = _get_config(base_config_id)
    try:
        config = IcpScoringConfig.objects.create(
            version=version,
            tags=base.tags,
            quality_investors=base.quality_investors,
            scoring_rules={"source": source},
            created_by_id=created_by_id,
            is_active=False,
        )
    except IntegrityError as error:
        raise DuplicateScoringVersion(
            "A scoring version with this name already exists. Choose another name."
        ) from error
    return _config_result(config)


def activate_scoring_formula(config_id: UUID) -> ScoringConfig:
    config = _get_config(config_id)
    config.activate()
    return _config_result(config)
