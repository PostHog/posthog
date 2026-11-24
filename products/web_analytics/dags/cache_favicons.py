import time
import datetime as dt
from typing import NamedTuple, cast
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.models.team import Team

from products.aeo.backend.facade.api import list_domains_across_teams
from products.customer_analytics.backend.facade.api import list_logo_domains_across_teams

# Matches the window the AI visibility pages report on.
AEO_CITED_DOMAINS_WINDOW = dt.timedelta(days=30)

# Any user who can create accounts adds domains to this job, so bound the whole list and each
# team's share of it, and leave domains with no favicon alone for a week instead of every hour.
ACCOUNT_DOMAINS_LIMIT = 500_000
ACCOUNT_DOMAINS_PER_TEAM_LIMIT = 50_000
ACCOUNT_FAILED_DOMAIN_RETRY_AFTER = dt.timedelta(days=7)
# Stops starting new downloads before the next hourly run is due; the backlog continues next run.
ACCOUNT_FAVICONS_RUN_TIME_BUDGET = dt.timedelta(minutes=50)
# A run older than this is treated as stuck, so it does not block the schedule for ever.
ACCOUNT_FAVICONS_STUCK_RUN_AGE = dt.timedelta(hours=6)


def get_last_cached_domains(context: dagster.AssetExecutionContext, asset_key: str) -> set[str]:
    last_mat = context.instance.get_latest_materialization_event(dagster.AssetKey([asset_key]))
    if not last_mat or not last_mat.asset_materialization:
        return set()

    metadata = last_mat.asset_materialization.metadata
    cached_domains_meta = metadata.get("cached_domains")
    if cached_domains_meta and isinstance(cached_domains_meta, dagster.JsonMetadataValue):
        return set(cast(list[str], cached_domains_meta.value))
    return set()


def get_recently_failed_domains(
    context: dagster.AssetExecutionContext, asset_key: str, now: dt.datetime
) -> dict[str, str]:
    """Domains whose favicon download failed within the retry window, mapped to the failure date."""
    last_mat = context.instance.get_latest_materialization_event(dagster.AssetKey([asset_key]))
    if not last_mat or not last_mat.asset_materialization:
        return {}

    failed_meta = last_mat.asset_materialization.metadata.get("failed_domains")
    if not failed_meta or not isinstance(failed_meta, dagster.JsonMetadataValue):
        return {}
    retry_from = (now - ACCOUNT_FAILED_DOMAIN_RETRY_AFTER).date().isoformat()
    return {
        domain: failed_on
        for domain, failed_on in cast(dict[str, str], failed_meta.value).items()
        if failed_on > retry_from
    }


def get_authorized_domains(context: dagster.AssetExecutionContext) -> set[str]:
    """Extract unique domains from all teams' authorized URL lists (app_urls)."""
    domains: set[str] = set()
    for app_urls in Team.objects.exclude(app_urls=[]).values_list("app_urls", flat=True).iterator():
        for url in app_urls:
            if not url:
                continue
            # Skip wildcard patterns — we can't fetch a favicon for *.example.com
            if "*" in url:
                continue
            # Add a scheme if missing so urlparse can extract the hostname
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            try:
                parsed = urlparse(url)
                if parsed.hostname:
                    domains.add(parsed.hostname)
            except Exception:
                context.log.debug(f"Skipping unparseable authorized URL: {url}")
    return domains


class CacheFaviconsConfig(dagster.Config):
    force_refresh: bool = False


def download_favicon(
    context: dagster.AssetExecutionContext, domain: str, client: httpx.Client
) -> tuple[str, bytes | None, str | None, str | None]:
    context.log.info(f"Attempting to download favicon for domain '{domain}'")
    urls = [
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
        f"https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{domain}&size=32",
    ]

    for url in urls:
        try:
            resp = client.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                context.log.info(f"Found favicon for {domain} at {url}")
                return domain, resp.content, resp.headers.get("content-type"), url
        except Exception:
            context.log.exception(f"Failed to download favicon from: {url}")
            continue

    return domain, None, None, None


def upload_if_missing(context: dagster.AssetExecutionContext, s3_client, bucket, key, data, content_type):
    context.log.info(f"Attempting to cache {key}")
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        context.log.info("Favicon already cached, skipping upload.")
        return key
    except s3_client.exceptions.ClientError:
        pass

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    context.log.info("Favicon successfully cached.")
    return key


class FaviconCacheRun(NamedTuple):
    favicons: list[dict]
    cached_domains: set[str]
    skipped_count: int
    failed_domains: set[str]
    out_of_time: bool


def _download_and_cache_favicons(
    context: dagster.AssetExecutionContext,
    s3: S3Resource,
    domains: list[str],
    previously_cached: set[str],
    time_budget: dt.timedelta | None = None,
) -> FaviconCacheRun:
    """Download and cache favicons for a list of domains. With a time budget, stops starting new
    downloads once it is spent and reports `out_of_time`."""
    s3_client = s3.get_client()
    bucket = settings.DAGSTER_FAVICONS_S3_BUCKET
    deadline = time.monotonic() + time_budget.total_seconds() if time_budget is not None else None

    favicons: list[dict] = []
    all_cached_domains = previously_cached.copy()
    skipped_count = 0
    failed_domains: set[str] = set()

    with httpx.Client() as client:
        for domain in domains:
            if domain in previously_cached:
                context.log.debug(f"Skipping download for '{domain}' - already cached.")
                skipped_count += 1
                continue

            if deadline is not None and time.monotonic() >= deadline:
                context.log.info("Time budget spent, leaving the remaining domains for the next run.")
                return FaviconCacheRun(favicons, all_cached_domains, skipped_count, failed_domains, True)

            domain, data, content_type, source_url = download_favicon(context, domain, client)
            if data is None:
                failed_domains.add(domain)
                continue

            key = f"favicons/{domain}"
            upload_if_missing(context, s3_client, bucket, key, data, content_type)
            all_cached_domains.add(domain)
            favicons.append(
                {
                    "domain": domain,
                    "source_url": source_url,
                    "cached_url": f"s3://{bucket}{key}",
                    "favicon_url": f"/static/favicons/{domain}",
                }
            )

    return FaviconCacheRun(favicons, all_cached_domains, skipped_count, failed_domains, False)


@dagster.asset
def cache_favicons(
    context: dagster.AssetExecutionContext, s3: S3Resource, config: CacheFaviconsConfig
) -> dagster.MaterializeResult:
    # We have over 10M distinct referrers for recent data, so let's limit to the top 50k to keep this manageable while we test it
    # https://metabase.prod-us.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiJXSVRIIHJlZmVycmVycyBBUyAoXG4gICAgU0VMRUNUXG4gICAgICAgIGRvbWFpbihtYXRfJHJlZmVycmVyKSBBUyByZWZlcnJlcixcbiAgICAgICAgY291bnQoKSBBUyBjbnRcbiAgICBGUk9NIGV2ZW50c1xuICAgIFdIRVJFIGV2ZW50ID0gJyRwYWdldmlldydcbiAgICAgICAgQU5EIHRpbWVzdGFtcCA-PSBub3coKSAtIElOVEVSVkFMIDkwIERBWVxuICAgICAgICBBTkQgbWF0XyRyZWZlcnJlciBJUyBOT1QgTlVMTFxuICAgICAgICBBTkQgbWF0XyRyZWZlcnJlciAhPSAnJ1xuICAgIEdST1VQIEJZIHJlZmVycmVyXG4pLFxucmFua2VkIEFTIChcbiAgICBTRUxFQ1RcbiAgICAgICAgcmVmZXJyZXIsXG4gICAgICAgIGNudCxcbiAgICAgICAgc3VtKGNudCkgT1ZFUiAoT1JERVIgQlkgY250IERFU0MpIEFTIHJ1bm5pbmdfY250LFxuICAgICAgICBzdW0oY250KSBPVkVSICgpIEFTIHRvdGFsX2NudFxuICAgIEZST00gcmVmZXJyZXJzXG4pXG5TRUxFQ1RcbiAgICByZWZlcnJlcixcbiAgICBjbnQsXG4gICAgcnVubmluZ19jbnQgLyB0b3RhbF9jbnQgQVMgY3VtdWxhdGl2ZV9zaGFyZVxuRlJPTSByYW5rZWRcbk9SREVSIEJZIGNudCBERVNDIiwidGVtcGxhdGUtdGFncyI6e319LCJkYXRhYmFzZSI6Mzh9LCJkaXNwbGF5Ijoic2NhbGFyIiwicGFyYW1ldGVycyI6W10sInZpc3VhbGl6YXRpb25fc2V0dGluZ3MiOnt9fQ==
    top_referrer_query = """
        SELECT
            domain(mat_$referrer) AS referrer,
            count(*) AS count
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= now() - interval 90 day
            AND referrer is not null and referrer != ''
        GROUP BY referrer
        ORDER BY count DESC
        LIMIT 50000
    """

    context.log.info("Querying top referrers.")
    results = sync_execute(top_referrer_query)
    context.log.info(f"Found {len(results)} domains.")

    previously_cached = set() if config.force_refresh else get_last_cached_domains(context, "cache_favicons")
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")

    domains = [domain for domain, _count in results]
    favicons, all_cached_domains, skipped_count, _, _ = _download_and_cache_favicons(
        context, s3, domains, previously_cached
    )

    context.log.info(f"Successfully cached {len(favicons)} new favicons, skipped {skipped_count} already cached.")

    top_domains = [{"domain": domain, "pageviews": count} for domain, count in results[:20]]

    return dagster.MaterializeResult(
        metadata={
            "domains_queried": len(results),
            "favicons_cached": len(favicons),
            "domains_skipped": skipped_count,
            "top_domains": top_domains,
            "cached_domains": list(all_cached_domains),
            "favicons": favicons,
        }
    )


@dagster.asset
def cache_authorized_domain_favicons(
    context: dagster.AssetExecutionContext, s3: S3Resource, config: CacheFaviconsConfig
) -> dagster.MaterializeResult:
    context.log.info("Querying authorized domains from team settings.")
    authorized_domains = get_authorized_domains(context)
    context.log.info(f"Found {len(authorized_domains)} authorized domains.")

    previously_cached = (
        set() if config.force_refresh else get_last_cached_domains(context, "cache_authorized_domain_favicons")
    )
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")

    favicons, all_cached_domains, skipped_count, _, _ = _download_and_cache_favicons(
        context, s3, list(authorized_domains), previously_cached
    )

    context.log.info(f"Successfully cached {len(favicons)} new favicons, skipped {skipped_count} already cached.")

    return dagster.MaterializeResult(
        metadata={
            "authorized_domains_queried": len(authorized_domains),
            "favicons_cached": len(favicons),
            "domains_skipped": skipped_count,
            "cached_domains": list(all_cached_domains),
            "favicons": favicons,
        }
    )


@dagster.asset
def cache_aeo_domain_favicons(
    context: dagster.AssetExecutionContext, s3: S3Resource, config: CacheFaviconsConfig
) -> dagster.MaterializeResult:
    context.log.info("Querying AI visibility brand and cited domains.")
    aeo_domains = list_domains_across_teams(cited_since=timezone.now() - AEO_CITED_DOMAINS_WINDOW)
    context.log.info(f"Found {len(aeo_domains)} AI visibility domains.")

    previously_cached = set() if config.force_refresh else get_last_cached_domains(context, "cache_aeo_domain_favicons")
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")

    favicons, all_cached_domains, skipped_count, _, _ = _download_and_cache_favicons(
        context, s3, aeo_domains, previously_cached
    )

    context.log.info(f"Successfully cached {len(favicons)} new favicons, skipped {skipped_count} already cached.")

    return dagster.MaterializeResult(
        metadata={
            "aeo_domains_queried": len(aeo_domains),
            "favicons_cached": len(favicons),
            "domains_skipped": skipped_count,
            "cached_domains": list(all_cached_domains),
            "favicons": favicons,
        }
    )


@dagster.asset
def cache_account_domain_favicons(
    context: dagster.AssetExecutionContext, s3: S3Resource, config: CacheFaviconsConfig
) -> dagster.MaterializeResult:
    context.log.info("Querying customer analytics account domains.")
    account_domains = list_logo_domains_across_teams(
        limit=ACCOUNT_DOMAINS_LIMIT, per_team_limit=ACCOUNT_DOMAINS_PER_TEAM_LIMIT
    )
    context.log.info(f"Found {len(account_domains)} account domains.")

    asset_key = "cache_account_domain_favicons"
    previously_cached = set() if config.force_refresh else get_last_cached_domains(context, asset_key)
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")
    now = timezone.now()
    recently_failed = {} if config.force_refresh else get_recently_failed_domains(context, asset_key, now)
    domains = [domain for domain in account_domains if domain not in recently_failed]

    run = _download_and_cache_favicons(
        context, s3, domains, previously_cached, time_budget=ACCOUNT_FAVICONS_RUN_TIME_BUDGET
    )
    failed_domains = recently_failed | {domain: now.date().isoformat() for domain in run.failed_domains}

    context.log.info(
        f"Successfully cached {len(run.favicons)} new favicons, skipped {run.skipped_count} already cached, "
        f"{len(run.failed_domains)} failed, {len(recently_failed)} held back after a recent failure."
    )

    return dagster.MaterializeResult(
        metadata={
            "account_domains_queried": len(account_domains),
            "favicons_cached": len(run.favicons),
            "domains_skipped": run.skipped_count,
            "domains_failed": len(run.failed_domains),
            "domains_held_back": len(recently_failed),
            "out_of_time": run.out_of_time,
            "cached_domains": list(run.cached_domains),
            "failed_domains": failed_domains,
            "favicons": run.favicons,
        }
    )


cache_favicons_job = dagster.define_asset_job(
    name="cache_favicons_job",
    selection=["cache_favicons"],
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)

cache_authorized_domain_favicons_job = dagster.define_asset_job(
    name="cache_authorized_domain_favicons_job",
    selection=["cache_authorized_domain_favicons"],
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)

cache_aeo_domain_favicons_job = dagster.define_asset_job(
    name="cache_aeo_domain_favicons_job",
    selection=["cache_aeo_domain_favicons"],
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)

cache_account_domain_favicons_job = dagster.define_asset_job(
    name="cache_account_domain_favicons_job",
    selection=["cache_account_domain_favicons"],
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="37 3 * * *",  # Daily at 03:37 UTC
    job=cache_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)
def cache_favicons_schedule(_context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()


@dagster.schedule(
    cron_schedule="51 */6 * * *",  # Every 6 hours
    job=cache_authorized_domain_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)
def cache_authorized_domain_favicons_schedule(_context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()


@dagster.schedule(
    cron_schedule="23 * * * *",  # Hourly; only domains not cached yet are downloaded
    job=cache_aeo_domain_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)
def cache_aeo_domain_favicons_schedule(_context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()


@dagster.schedule(
    cron_schedule="47 * * * *",  # Hourly; only domains not cached yet are downloaded
    job=cache_account_domain_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)
def cache_account_domain_favicons_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    active_runs = context.instance.get_runs(
        dagster.RunsFilter(
            job_name=cache_account_domain_favicons_job.name,
            statuses=[
                dagster.DagsterRunStatus.QUEUED,
                dagster.DagsterRunStatus.NOT_STARTED,
                dagster.DagsterRunStatus.STARTING,
                dagster.DagsterRunStatus.STARTED,
            ],
            created_after=timezone.now() - ACCOUNT_FAVICONS_STUCK_RUN_AGE,
        ),
        limit=1,
    )
    if active_runs:
        return dagster.SkipReason(f"Run {active_runs[0].run_id} is still queued or executing.")
    return dagster.RunRequest()
