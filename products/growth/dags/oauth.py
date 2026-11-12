import time
from datetime import datetime, timedelta
from typing import Any, cast

from django.conf import settings
from django.db.models import Exists, Model, OuterRef, Q, QuerySet
from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthDeviceGrant,
    OAuthGrant,
    OAuthIDToken,
    OAuthRefreshToken,
)
from posthog.models.organization_provisioning import OrganizationProvisioning
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig


def batch_delete_model(queryset: QuerySet, query: Q, context: dagster.OpExecutionContext, token_type: str) -> int:
    """Delete tokens in batches to avoid locking up the tables."""
    CLEAR_EXPIRED_TOKENS_BATCH_SIZE = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_SIZE", 1000)
    CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL", 0.1)

    current_no = start_no = queryset.count()
    context.log.info(f"Starting deletion of {start_no} {token_type}")

    while current_no:
        flat_queryset = queryset.values_list("id", flat=True)[:CLEAR_EXPIRED_TOKENS_BATCH_SIZE]
        batch_length = flat_queryset.count()

        if batch_length == 0:
            break

        cast(Any, queryset.model).objects.filter(id__in=list(flat_queryset)).delete()
        context.log.debug(f"{batch_length} {token_type} deleted, {current_no - batch_length} left")

        queryset = cast(Any, queryset.model).objects.filter(query)
        time.sleep(CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL)
        current_no = queryset.count()

    stop_no = cast(Any, queryset.model).objects.filter(query).count()
    deleted = start_no - stop_no
    return deleted


def clear_expired_tokens_by_type(
    model: type[Model], queries: dict[str, Q], context: dagster.OpExecutionContext
) -> dict[str, int]:
    """Clear expired tokens for a specific model type using multiple queries."""
    results = {}

    for query_name, query in queries.items():
        queryset = cast(Any, model).objects.filter(query)
        deleted_count = batch_delete_model(queryset, query, context, f"{model.__name__} {query_name}")
        results[query_name] = deleted_count
        context.log.info(f"{deleted_count} {model.__name__} {query_name} deleted")

    return results


@dagster.op
def clear_expired_oauth_tokens(context: dagster.OpExecutionContext) -> None:
    """
    Clear expired OAuth tokens from the database.
    This function deletes expired refresh tokens, access tokens, ID tokens, grants and device grants
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
        (
            OAuthDeviceGrant,
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
    cron_schedule="19 2 * * *",
    execution_timezone="UTC",
    name="oauth_cleanup_daily_schedule",
)


def stale_oauth_applications(now: datetime) -> QuerySet:
    """Self-registered (DCR and CIMD) applications with no token that is valid now or was
    valid inside the grace period.

    Only self-registered clients qualify. A client that is deleted can register again: a CIMD
    client is created again on its next authorization, and a DCR client calls the registration
    endpoint again. Apps that PostHog staff or an organization set up, partners, and apps that
    other rows still point at are never candidates.
    """
    cutoff = now - timedelta(seconds=settings.OAUTH_STALE_APPLICATION_GRACE_PERIOD)
    app = OuterRef("pk")
    return (
        OAuthApplication.objects.filter(
            Q(is_dcr_client=True) | Q(is_cimd_client=True),
            created__lt=cutoff,
            organization__isnull=True,
            is_first_party=False,
            is_verified=False,
            is_provisioning_partner=False,
            _provisioning_config={},
            can_manage_ema_issuer=False,
        )
        .exclude(Exists(OAuthAccessToken.objects.filter(application=app, expires__gte=cutoff)))
        # An unrevoked refresh token can still mint access tokens, whatever its age.
        .exclude(
            Exists(
                OAuthRefreshToken.objects.filter(application=app).filter(
                    Q(revoked__isnull=True) | Q(revoked__gte=cutoff)
                )
            )
        )
        .exclude(Exists(OAuthIDToken.objects.filter(application=app, expires__gte=cutoff)))
        .exclude(Exists(OAuthGrant.objects.filter(application=app, expires__gte=cutoff)))
        .exclude(Exists(OAuthDeviceGrant.objects.filter(client_id=OuterRef("client_id"), expires__gte=cutoff)))
        .exclude(Exists(OrganizationProvisioning.objects.filter(application=app)))
        .exclude(Exists(TeamProvisioningConfig.objects.filter(application=app)))
        .exclude(Exists(IdentityProviderConfig.objects.filter(id_jag_registered_by_application=app)))
    )


class ClearStaleOAuthApplicationsConfig(dagster.Config):
    dry_run: bool = False


@dagster.op
def clear_stale_oauth_applications(
    context: dagster.OpExecutionContext, config: ClearStaleOAuthApplicationsConfig
) -> None:
    """Delete self-registered OAuth applications that no longer have a valid token."""
    batch_size = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_SIZE", 1000)
    batch_interval = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL", 0.1)
    now = timezone.now()

    candidates = stale_oauth_applications(now)
    found = candidates.count()
    found_cimd = candidates.filter(is_cimd_client=True).count()
    context.log.info(f"Found {found} stale OAuth applications ({found_cimd} CIMD, {found - found_cimd} DCR)")

    deleted = 0
    if not config.dry_run:
        # Walk forward by primary key, so an app that is kept is checked once rather than again in
        # every batch.
        candidates = stale_oauth_applications(now).order_by("id")
        last_id = None
        while ids := list(
            (candidates.filter(id__gt=last_id) if last_id else candidates).values_list("id", flat=True)[:batch_size]
        ):
            # Re-check each batch, so an app that got a token after the count above is kept.
            deleted += OAuthApplication.objects.filter(id__in=ids).delete()[1].get(OAuthApplication._meta.label, 0)
            last_id = ids[-1]
            context.log.debug(f"{deleted} stale OAuth applications deleted")
            time.sleep(batch_interval)

    context.log.info(f"Stale OAuth applications deleted: {deleted}")
    context.add_output_metadata(
        {
            "stale_applications_found": dagster.MetadataValue.int(found),
            "stale_cimd_applications_found": dagster.MetadataValue.int(found_cimd),
            "stale_applications_deleted": dagster.MetadataValue.int(deleted),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def oauth_clear_stale_oauth_applications_job():
    clear_stale_oauth_applications()


oauth_clear_stale_oauth_applications_schedule = dagster.ScheduleDefinition(
    job=oauth_clear_stale_oauth_applications_job,
    cron_schedule="49 2 * * *",
    execution_timezone="UTC",
    name="oauth_stale_application_cleanup_daily_schedule",
)
