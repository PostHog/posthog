import time
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.db.models import Model, Q, QuerySet
from django.utils import timezone

import dagster
from oauth2_provider.settings import oauth2_settings

from posthog.dags.common import JobOwners
from posthog.models.oauth import OAuthAccessToken, OAuthGrant, OAuthIDToken, OAuthRefreshToken


def batch_delete_model(queryset: QuerySet, context: dagster.OpExecutionContext, token_type: str) -> int:
    """Delete tokens in batches to avoid locking up the tables."""
    batch_size = oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_SIZE
    batch_interval = oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL

    manager = cast(Any, queryset.model).objects
    deleted = 0

    while True:
        ids = list(queryset.values_list("id", flat=True)[:batch_size])
        if not ids:
            break

        manager.filter(id__in=ids).delete()
        deleted += len(ids)
        context.log.debug(f"{len(ids)} {token_type} deleted, {deleted} in total")

        time.sleep(batch_interval)

    return deleted


def clear_expired_tokens_by_type(
    model: type[Model], queries: dict[str, Q], context: dagster.OpExecutionContext
) -> dict[str, int]:
    """Clear expired tokens for a specific model type using multiple queries."""
    results = {}

    for query_name, query in queries.items():
        queryset = cast(Any, model).objects.filter(query)
        deleted_count = batch_delete_model(queryset, context, f"{model.__name__} {query_name}")
        results[query_name] = deleted_count
        context.log.info(f"{deleted_count} {model.__name__} {query_name} deleted")

    return results


@dagster.op
def clear_expired_oauth_tokens(context: dagster.OpExecutionContext) -> None:
    """
    Clear expired OAuth tokens from the database.
    This function deletes expired refresh tokens, access tokens, ID tokens, and grants
    """
    now = timezone.now()
    retention_cutoff = now - timedelta(seconds=settings.OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD)

    refresh_token_expiry_cutoff = now - timedelta(
        seconds=int(str(settings.OAUTH2_PROVIDER["REFRESH_TOKEN_EXPIRE_SECONDS"]))
        + settings.OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD
    )

    context.log.info(f"Clearing OAuth tokens expired before {retention_cutoff}")

    token_operations: list[tuple[type[Model], dict[str, Q]]] = [
        (
            OAuthRefreshToken,
            {
                "revoked": Q(revoked__lt=retention_cutoff),
                "expired_via_access_token": Q(access_token__expires__lt=refresh_token_expiry_cutoff),
                # Revoking an access token deletes the row, and this side of the OneToOne is
                # SET_NULL, so a refresh token can lose the join the query above reaches it by
                # while staying valid: validate_refresh_token never compares against created.
                "expired_orphaned": Q(
                    access_token__isnull=True,
                    revoked__isnull=True,
                    created__lt=refresh_token_expiry_cutoff,
                ),
            },
        ),
        (
            OAuthAccessToken,
            {
                "expired_standalone": Q(refresh_token__isnull=True, expires__lt=retention_cutoff),
            },
        ),
        (
            OAuthIDToken,
            {
                "expired_standalone": Q(access_token__isnull=True, expires__lt=retention_cutoff),
            },
        ),
        (
            OAuthGrant,
            {
                "expired": Q(expires__lt=retention_cutoff),
            },
        ),
    ]

    total_deleted = 0
    for model, queries in token_operations:
        results = clear_expired_tokens_by_type(model, queries, context)
        total_deleted += sum(results.values())

    context.log.info(f"Total tokens deleted: {total_deleted}")

    context.add_output_metadata(
        {
            "total_tokens_deleted": dagster.MetadataValue.int(total_deleted),
            "retention_cutoff": dagster.MetadataValue.text(retention_cutoff.isoformat()),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def oauth_clear_expired_oauth_tokens_job():
    clear_expired_oauth_tokens()


oauth_clear_expired_oauth_tokens_schedule = dagster.ScheduleDefinition(
    job=oauth_clear_expired_oauth_tokens_job,
    cron_schedule="0 2 * * *",
    execution_timezone="UTC",
    name="oauth_cleanup_daily_schedule",
)
