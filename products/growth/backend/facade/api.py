import uuid
import datetime as dt
from collections.abc import Iterator
from typing import Any

import redis

from products.growth.backend import constants, sdk_health
from products.growth.backend.facade import contracts
from products.growth.backend.product_push import selection


def run_label_batch(
    label: str,
    *,
    limit: int | None,
    workers: int,
    max_failures: int,
    expected_version: str | None,
) -> contracts.LabelBatchSummary:
    from products.growth.backend.enrichment import label_batch

    return label_batch.run_label_batch(
        label, limit=limit, workers=workers, max_failures=max_failures, expected_version=expected_version
    )


def iter_label_dry_run(
    label: str, *, sample: int, prompt_file: str | None, compare_version: str | None
) -> contracts.LabelDryRun:
    from products.growth.backend.enrichment import lab

    return lab.dry_run(label, sample=sample, prompt_file=prompt_file, compare_version=compare_version)


def ensure_fit_backfill_allowed() -> None:
    from products.growth.backend.enrichment import fit_backfill

    fit_backfill.ensure_backfill_allowed()


def backfill_icp_fit_scores(
    *, limit: int | None, delay: float, dry_run: bool, tags_csv: str | None, investors_csv: str | None
) -> Iterator[contracts.FitBackfillItem]:
    from products.growth.backend.enrichment import fit_backfill

    return fit_backfill.backfill_icp_fit_scores(
        limit=limit, delay=delay, dry_run=dry_run, tags_csv=tags_csv, investors_csv=investors_csv
    )


def score_parity(
    *, payloads: str, expected: str | None, tags_csv: str | None, investors_csv: str | None
) -> contracts.ParityRun:
    from products.growth.backend.enrichment import fit_backfill

    return fit_backfill.score_parity(
        payloads=payloads, expected=expected, tags_csv=tags_csv, investors_csv=investors_csv
    )


def ensure_fields_backfill_allowed() -> None:
    from products.growth.backend.enrichment import fields_backfill

    fields_backfill.ensure_backfill_allowed()


def backfill_enrichment_fields(
    *, limit: int | None, delay: float, dry_run: bool
) -> Iterator[contracts.FieldsBackfillItem]:
    from products.growth.backend.enrichment import fields_backfill

    return fields_backfill.backfill_enrichment_fields(limit=limit, delay=delay, dry_run=dry_run)


def ensure_signup_backfill_allowed() -> None:
    from products.growth.backend.enrichment import signup_backfill

    signup_backfill.ensure_backfill_allowed()


def iter_signups_missing_enrichment(
    *, after: dt.datetime, before: dt.datetime
) -> Iterator[contracts.SignupCandidate | contracts.SignupSkip]:
    from products.growth.backend.enrichment import signup_backfill

    return signup_backfill.iter_signups_missing_enrichment(after=after, before=before)


def dispatch_signup_enrichment(candidate: contracts.SignupCandidate) -> None:
    from products.growth.backend.enrichment import signup_backfill

    signup_backfill.dispatch(candidate)


def backfill_harmonic_ownership(
    *, after_id: str | None, limit: int, dry_run: bool, sleep_seconds: float
) -> contracts.OwnershipBackfill:
    from products.growth.backend.enrichment import ownership_backfill

    return ownership_backfill.backfill_harmonic_ownership(
        after_id=after_id, limit=limit, dry_run=dry_run, sleep_seconds=sleep_seconds
    )


def create_icp_scoring_lists(
    *, version: str, tags_csv: str, investors_csv: str, activate: bool
) -> contracts.ScoringListsCreated:
    from products.growth.backend.enrichment import icp_lists_sync

    return icp_lists_sync.create_icp_scoring_lists(
        version=version, tags_csv=tags_csv, investors_csv=investors_csv, activate=activate
    )


def ensure_label_config(
    *,
    name: str,
    version: str,
    prompt_text: str,
    model: str,
    input_fields: list[str],
    output_fields: list[dict[str, Any]],
) -> bool:
    from products.growth.backend.enrichment import prompt_config

    return prompt_config.ensure_prompt_config(
        name=name,
        version=version,
        prompt_text=prompt_text,
        model=model,
        input_fields=input_fields,
        output_fields=output_fields,
    )


def active_product_push_campaigns(
    organization_id: str | uuid.UUID, *, started_before: dt.datetime
) -> tuple[contracts.ProductPushCampaignSummary, ...]:
    from products.growth.backend.product_push import service

    return tuple(
        contracts.ProductPushCampaignSummary(product_key=product_key, reason_text=reason_text)
        for product_key, reason_text in service.active_campaigns(organization_id, started_before=started_before)
    )


def resolve_product_path(product_key: str) -> str | None:
    return selection.resolve_product_path(product_key)


def project_uses_product(project_id: int, product_key: str, organization_id: str | uuid.UUID) -> bool:
    return selection.project_uses_product(project_id, product_key, organization_id)


def compute_sdk_health(
    combined_data: dict[str, dict[str, Any]], *, now: dt.datetime | None = None, project_id: int | None = None
) -> contracts.SdkHealthReport:
    return sdk_health.compute_sdk_health(combined_data, now=now, project_id=project_id)


def get_and_cache_team_sdk_versions(
    team_id: int, redis_client: redis.Redis
) -> dict[str, list[contracts.SdkVersionEntry]] | None:
    # Pulls posthog.hogql.query, the direct-SQL adapters, and ee.clickhouse.materialized_columns,
    # none of which the SDK health view needs until it reads a cold cache.
    from products.growth.backend.team_sdk_versions import get_and_cache_team_sdk_versions as get_and_cache

    return get_and_cache(team_id, redis_client)


def github_sdk_versions_cache_key(sdk_type: str) -> str:
    return constants.github_sdk_versions_key(sdk_type)


def team_sdk_versions_cache_key(team_id: int) -> str:
    return constants.team_sdk_versions_v2_key(team_id)
