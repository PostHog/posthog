import time

from django.db import migrations

BATCH_SIZE = 2000

# Snapshot of each source type's implemented vendor API version at the time this migration was
# written (the source classes' `default_version`). Frozen here so the backfill is deterministic
# and never depends on importing application code. Types not listed were unversioned at snapshot
# time and pin to DEFAULT_API_VERSION.
DEFAULT_API_VERSION = "v1"

API_VERSION_BY_SOURCE_TYPE = {
    "ActiveCampaign": "v3",
    "Airtable": "v0",
    "ApifyDataset": "v2",
    "Asana": "1.0",
    "Attio": "v2",
    "Beamer": "v0",
    "BingAds": "v13",
    "Braintree": "2019-01-01",
    "Brevo": "v3",
    "CampaignMonitor": "v3.3",
    "CapsuleCRM": "v2",
    "Chargebee": "v2",
    "CircleCI": "v2",
    "Clari": "v4",
    "ClickUp": "v2",
    "Cloudflare": "v4",
    "CoinGecko": "v3",
    "Confluence": "v2",
    "ConvertKit": "v4",
    "Crunchbase": "v4",
    "Deel": "v2",
    "DevinAI": "v3",
    "Drip": "v2",
    "Eventbrite": "v3",
    "Freshdesk": "v2",
    "FullStory": "v2",
    "GitLab": "v4",
    "Github": "2022-11-28",
    "GoCardless": "2015-07-06",
    "Gong": "v2",
    "GoogleAds": "v23",
    "GoogleSearchConsole": "v3",
    "Hubspot": "v3",
    "Inflowinventory": "2023-04-01",
    "Insightly": "v3.1",
    "Intercom": "2.13",
    "Jira": "3",
    "Klaviyo": "2024-10-15",
    "LaunchDarkly": "v2",
    "LightspeedRetail": "2.0",
    "Mailchimp": "3.0",
    "Mailgun": "v3",
    "Mailjet": "v3",
    "MetaAds": "v25.0",
    "Mollie": "v2",
    "Monday": "v2",
    "NewsApi": "v2",
    "NewsData": "1",
    "NorthpassLMS": "v2",
    "Notion": "2025-09-03",
    "Omnisend": "v3",
    "OpinionStage": "v2",
    "Optimizely": "v2",
    "Oura": "v2",
    "Outbrain": "v0.1",
    "PagerDuty": "2",
    "PartnerStack": "v2",
    "Personio": "v2",
    "Pingdom": "3.1",
    "PinterestAds": "v5",
    "Productboard": "v2",
    "Recharge": "2021-11",
    "Recurly": "v2021-02-25",
    "RedditAds": "v3",
    "RevenueCat": "v2",
    "Rocketlane": "1.0",
    "Rollbar": "1",
    "SalesLoft": "v2",
    "Salesforce": "v61.0",
    "SendGrid": "v3",
    "Sentry": "0",
    "Shopify": "2025-10",
    "Shortcut": "v3",
    "Smartsheet": "2.0",
    "Square": "v2",
    "Stripe": "2024-09-30.acacia",
    "SurveyMonkey": "v3",
    "Taboola": "1.0",
    "Tavus": "v2",
    "Teamtailor": "20240404",
    "TikTokAds": "v1.3",
    "Trello": "1",
    "Twilio": "2010-04-01",
    "Webflow": "v2",
    "WooCommerce": "v3",
    "Wordpress": "v2",
    "Wrike": "v4",
    "Wufoo": "v3",
    "Zendesk": "v2",
    "Zoom": "v2",
}


def backfill_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Batched like 0029 so we never hold row locks across the whole table at once — Temporal
    # activities and token refreshes write these rows continuously. The isnull guard makes each
    # batch idempotent (safe under retries, with atomic=False each batch commits independently)
    # and ensures rows pinned after this migration was written are never overwritten.
    source_types = ExternalDataSource.objects.values_list("source_type", flat=True).distinct()
    for source_type in source_types:
        version = API_VERSION_BY_SOURCE_TYPE.get(source_type, DEFAULT_API_VERSION)
        while True:
            batch_ids = list(
                ExternalDataSource.objects.filter(source_type=source_type, api_version__isnull=True).values_list(
                    "id", flat=True
                )[:BATCH_SIZE]
            )
            if not batch_ids:
                break
            ExternalDataSource.objects.filter(id__in=batch_ids).update(api_version=version)
            time.sleep(0.1)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("warehouse_sources", "0063_externaldatasource_api_version")]

    operations = [
        # Reverse is a no-op: 0063's reverse drops the column anyway, and nulling pins that merely
        # match the snapshot would also destroy legitimate creation-time stamps made after this ran.
        migrations.RunPython(backfill_api_version, migrations.RunPython.noop, elidable=True),
    ]
