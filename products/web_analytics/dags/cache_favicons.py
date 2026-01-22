from typing import Optional

from django.conf import settings

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client import sync_execute


def download_favicon(
    context: dagster.AssetExecutionContext, domain: str, client: httpx.Client
) -> tuple[str, Optional[bytes], Optional[str], Optional[str]]:
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
def cache_favicons(context: dagster.AssetExecutionContext, s3: S3Resource) -> dagster.MaterializeResult:
    top_referrer_query = """
        SELECT cutToFirstSignificantSubdomainWithWWW(mat_$referrer) AS referrer
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= now() - interval 90 day
            AND referrer is not null and referrer != ''
        GROUP BY referrer
        HAVING count(*) > 1000
        LIMIT 5000
    """

    context.log.info("Querying top referrers.")
    results = sync_execute(top_referrer_query)
    context.log.info(f"Found {len(results)} domains.")

    s3_client = s3.get_client()
    bucket = settings.DAGSTER_FAVICONS_S3_BUCKET

    favicons: list[dict] = []
    with httpx.Client() as client:
        for (domain,) in results:
            domain, data, content_type, source_url = download_favicon(context, domain, client)
            if data is None:
                continue
            key = f"favicons/{domain}.png"
            upload_if_missing(
                context,
                s3_client,
                bucket,
                key,
                data,
                content_type,
            )
            favicons.append(
                {
                    "domain": domain,
                    "source_url": source_url,
                    "cached_url": f"s3://{bucket}{key}",
                    "favicon_url": f"/static/favicons/{domain}.png",
                }
            )

    context.log.info(f"Successfully cached {len(favicons)} favicons.")

    return dagster.MaterializeResult(
        metadata={
            "domains_queried": len(results),
            "favicons_cached": len(favicons),
            "favicons": favicons,
        }
    )
