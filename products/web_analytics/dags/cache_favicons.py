from typing import Optional

from django.conf import settings

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster

logger = dagster.get_dagster_logger()


def download_favicon(domain: str, client: httpx.Client) -> tuple[str, Optional[bytes], Optional[str]]:
    logger.info(f"Attempting to download favicon for domain '{domain}'")
    urls = [
        f"https://www.google.com/s2/favicons?sz=32&domain=https://{domain}",
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
    ]

    for url in urls:
        try:
            resp = client.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                logger.info(f"Found favicon for {domain} at {url}")
                return domain, resp.content, resp.headers.get("content-type")
        except Exception:
            logger.exception(f"Failed to download favicon from: {url}")
            continue

    return domain, None, None


def upload_if_missing(s3_client, bucket, key, data, content_type):
    # Ignore uploading if the favicon already exists in our cache
    logger.info(f"Attempting to cache {key}")
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        logger.info("Favicon already cached, skipping upload.")
        return key
    except s3_client.exceptions.ClientError:
        pass

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    logger.info(f"Favicon successfully cached.")
    return key


@dagster.asset
def cache_favicons(s3: S3Resource, cluster: dagster.ResourceParam[ClickhouseCluster]):
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

    logger.info("Querying top referrers.")
    results = sync_execute(top_referrer_query)

    domains = [result[0] for result in results]
    logger.info(f"Found {len(domains)} results.")

    s3_client = s3.get_client()

    uploaded = []
    with httpx.Client() as client:
        for domain in domains:
            domain, data, content_type = download_favicon(domain, client)
            if data is None:
                continue
            key = f"/favicons/{domain}.png"
            upload_if_missing(
                s3_client,
                settings.DAGSTER_FAVICONS_S3_BUCKET,
                key,
                data,
                content_type,
            )
            uploaded.append(key)

    return uploaded
