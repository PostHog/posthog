from django.conf import settings

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners


def get_last_cached_domains(context: dagster.AssetExecutionContext) -> set[str]:
    last_mat = context.instance.get_latest_materialization_event(dagster.AssetKey(["cache_favicons"]))
    if not last_mat or not last_mat.asset_materialization:
        return set()

    metadata = last_mat.asset_materialization.metadata
    cached_domains_meta = metadata.get("cached_domains")
    if cached_domains_meta and isinstance(cached_domains_meta, dagster.JsonMetadataValue):
        return set(cached_domains_meta.value)
    return set()


class CacheFaviconsConfig(dagster.Config):
    force_refresh: bool = False


def download_favicon(
    context: dagster.AssetExecutionContext, domain: str, client: httpx.Client
) -> tuple[str, bytes | None, str | None, str | None]:
    context.log.info(f"Attempting to download favicon for domain '{domain}'")
    urls = [
        f"https://www.google.com/s2/favicons?sz=32&domain=https://{domain}",
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
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

    previously_cached = set() if config.force_refresh else get_last_cached_domains(context)
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")

    s3_client = s3.get_client()
    bucket = settings.DAGSTER_FAVICONS_S3_BUCKET

    favicons: list[dict] = []
    all_cached_domains = previously_cached.copy()
    skipped_count = 0

    with httpx.Client() as client:
        for domain, _count in results:
            if domain in previously_cached:
                context.log.debug(f"Skipping download for '{domain}' - already cached.")
                skipped_count += 1
                continue

            domain, data, content_type, source_url = download_favicon(context, domain, client)
            if data is None:
                continue

            key = f"favicons/{domain}"
            upload_if_missing(
                context,
                s3_client,
                bucket,
                key,
                data,
                content_type,
            )
            all_cached_domains.add(domain)
            favicons.append(
                {
                    "domain": domain,
                    "source_url": source_url,
                    "cached_url": f"s3://{bucket}{key}",
                    "favicon_url": f"/static/favicons/{domain}",
                }
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


cache_favicons_job = dagster.define_asset_job(
    name="cache_favicons_job",
    selection=["cache_favicons"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="0 3 * * *",  # Daily at 3 AM UTC
    job=cache_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def cache_favicons_schedule(_context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()
