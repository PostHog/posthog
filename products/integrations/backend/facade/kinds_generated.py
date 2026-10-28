"""Generated from `products/integrations/backend/facade/catalogue.py`. Do not edit by hand.

Run `hogli build:projections --only integration-kinds` after a change to the catalogue. Import
`IntegrationManager` from `facade/api.py`, not the classes here.
"""

from enum import StrEnum

from products.integrations.backend.facade.api_accessors import (
    AuthAccessor,
    IntegrationManagerBase,
    IntegrationReader,
    KindAccessor,
)
from products.integrations.backend.facade.enums import AuthType


class IntegrationKind(StrEnum):
    ANTHROPIC = "anthropic"
    APNS = "apns"
    APPLE_ADS = "apple-ads"
    AWS_REDSHIFT = "aws-redshift"
    AWS_S3 = "aws-s3"
    AZURE_BLOB = "azure-blob"
    BING_ADS = "bing-ads"
    CLICKUP = "clickup"
    CUSTOMERIO_APP = "customerio-app"
    CUSTOMERIO_TRACK = "customerio-track"
    CUSTOMERIO_WEBHOOK = "customerio-webhook"
    DATABRICKS = "databricks"
    EMAIL = "email"
    FIREBASE = "firebase"
    GITHUB = "github"
    GITLAB = "gitlab"
    GOOGLE_ADS = "google-ads"
    GOOGLE_ANALYTICS = "google-analytics"
    GOOGLE_CALENDAR = "google-calendar"
    GOOGLE_CLOUD_SERVICE_ACCOUNT = "google-cloud-service-account"
    GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
    GOOGLE_PUBSUB = "google-pubsub"
    GOOGLE_SEARCH_CONSOLE = "google-search-console"
    GOOGLE_SHEETS = "google-sheets"
    HELPSCOUT = "helpscout"
    HUBSPOT = "hubspot"
    INSTAGRAM = "instagram"
    INTERCOM = "intercom"
    JIRA = "jira"
    LINEAR = "linear"
    LINKEDIN_ADS = "linkedin-ads"
    META_ADS = "meta-ads"
    PARDOT = "pardot"
    PINTEREST_ADS = "pinterest-ads"
    POSTGRESQL = "postgresql"
    POSTHOG = "posthog"
    REDDIT_ADS = "reddit-ads"
    RESEND = "resend"
    S3_COMPATIBLE = "s3-compatible"
    SALESFORCE = "salesforce"
    SLACK = "slack"
    SLACK_POSTHOG_CODE = "slack-posthog-code"
    SNAPCHAT = "snapchat"
    SNOWFLAKE = "snowflake"
    STRIPE = "stripe"
    TIKTOK_ADS = "tiktok-ads"
    TWILIO = "twilio"
    TWITTER_ADS = "twitter-ads"
    VERCEL = "vercel"
    YOUTUBE_ANALYTICS = "youtube-analytics"


class AnthropicKind(KindAccessor):
    kind = "anthropic"
    token = AuthAccessor(kind="anthropic", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"anthropic"}))


class ApnsKind(KindAccessor):
    kind = "apns"
    credentials = AuthAccessor(kind="apns", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"apns"}))


class AppleAdsKind(KindAccessor):
    kind = "apple-ads"
    oauth = AuthAccessor(kind="apple-ads", auth_type=AuthType.OAUTH)  # the default
    credentials = AuthAccessor(kind="apple-ads", auth_type=AuthType.CREDENTIALS)
    any = IntegrationReader(kinds=frozenset({"apple-ads"}))


class AwsRedshiftKind(KindAccessor):
    kind = "aws-redshift"
    credentials = AuthAccessor(kind="aws-redshift", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"aws-redshift"}))


class AwsS3Kind(KindAccessor):
    kind = "aws-s3"
    credentials = AuthAccessor(kind="aws-s3", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"aws-s3"}))


class AzureBlobKind(KindAccessor):
    kind = "azure-blob"
    credentials = AuthAccessor(kind="azure-blob", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"azure-blob"}))


class BingAdsKind(KindAccessor):
    kind = "bing-ads"
    oauth = AuthAccessor(kind="bing-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"bing-ads"}))


class ClickupKind(KindAccessor):
    kind = "clickup"
    oauth = AuthAccessor(kind="clickup", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="clickup", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"clickup"}))


class CustomerioAppKind(KindAccessor):
    kind = "customerio-app"
    token = AuthAccessor(kind="customerio-app", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-app"}))


class CustomerioTrackKind(KindAccessor):
    kind = "customerio-track"
    token = AuthAccessor(kind="customerio-track", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-track"}))


class CustomerioWebhookKind(KindAccessor):
    kind = "customerio-webhook"
    token = AuthAccessor(kind="customerio-webhook", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-webhook"}))


class DatabricksKind(KindAccessor):
    kind = "databricks"
    token = AuthAccessor(kind="databricks", auth_type=AuthType.TOKEN)
    credentials = AuthAccessor(kind="databricks", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"databricks"}))


class EmailKind(KindAccessor):
    kind = "email"
    credentials = AuthAccessor(kind="email", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"email"}))


class FirebaseKind(KindAccessor):
    kind = "firebase"
    credentials = AuthAccessor(kind="firebase", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"firebase"}))


class GithubKind(KindAccessor):
    kind = "github"
    oauth = AuthAccessor(kind="github", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="github", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"github"}))


class GitlabKind(KindAccessor):
    kind = "gitlab"
    token = AuthAccessor(kind="gitlab", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"gitlab"}))


class GoogleAdsKind(KindAccessor):
    kind = "google-ads"
    oauth = AuthAccessor(kind="google-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"google-ads"}))


class GoogleAnalyticsKind(KindAccessor):
    kind = "google-analytics"
    oauth = AuthAccessor(kind="google-analytics", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"google-analytics"}))


class GoogleCalendarKind(KindAccessor):
    kind = "google-calendar"
    oauth = AuthAccessor(kind="google-calendar", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"google-calendar"}))


class GoogleCloudServiceAccountKind(KindAccessor):
    kind = "google-cloud-service-account"
    credentials = AuthAccessor(kind="google-cloud-service-account", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-cloud-service-account"}))


class GoogleCloudStorageKind(KindAccessor):
    kind = "google-cloud-storage"
    credentials = AuthAccessor(kind="google-cloud-storage", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-cloud-storage"}))


class GooglePubsubKind(KindAccessor):
    kind = "google-pubsub"
    credentials = AuthAccessor(kind="google-pubsub", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-pubsub"}))


class GoogleSearchConsoleKind(KindAccessor):
    kind = "google-search-console"
    oauth = AuthAccessor(kind="google-search-console", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"google-search-console"}))


class GoogleSheetsKind(KindAccessor):
    kind = "google-sheets"
    oauth = AuthAccessor(kind="google-sheets", auth_type=AuthType.OAUTH)  # the default
    credentials = AuthAccessor(kind="google-sheets", auth_type=AuthType.CREDENTIALS)
    any = IntegrationReader(kinds=frozenset({"google-sheets"}))


class HelpscoutKind(KindAccessor):
    kind = "helpscout"
    oauth = AuthAccessor(kind="helpscout", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"helpscout"}))


class HubspotKind(KindAccessor):
    kind = "hubspot"
    oauth = AuthAccessor(kind="hubspot", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"hubspot"}))


class InstagramKind(KindAccessor):
    kind = "instagram"
    oauth = AuthAccessor(kind="instagram", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"instagram"}))


class IntercomKind(KindAccessor):
    kind = "intercom"
    oauth = AuthAccessor(kind="intercom", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"intercom"}))


class JiraKind(KindAccessor):
    kind = "jira"
    oauth = AuthAccessor(kind="jira", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="jira", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"jira"}))


class LinearKind(KindAccessor):
    kind = "linear"
    oauth = AuthAccessor(kind="linear", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"linear"}))


class LinkedinAdsKind(KindAccessor):
    kind = "linkedin-ads"
    oauth = AuthAccessor(kind="linkedin-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"linkedin-ads"}))


class MetaAdsKind(KindAccessor):
    kind = "meta-ads"
    oauth = AuthAccessor(kind="meta-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"meta-ads"}))


class PardotKind(KindAccessor):
    kind = "pardot"
    oauth = AuthAccessor(kind="pardot", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"pardot"}))


class PinterestAdsKind(KindAccessor):
    kind = "pinterest-ads"
    oauth = AuthAccessor(kind="pinterest-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"pinterest-ads"}))


class PostgresqlKind(KindAccessor):
    kind = "postgresql"
    credentials = AuthAccessor(kind="postgresql", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"postgresql"}))


class PosthogKind(KindAccessor):
    kind = "posthog"
    oauth = AuthAccessor(kind="posthog", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"posthog"}))


class RedditAdsKind(KindAccessor):
    kind = "reddit-ads"
    oauth = AuthAccessor(kind="reddit-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"reddit-ads"}))


class ResendKind(KindAccessor):
    kind = "resend"
    oauth = AuthAccessor(kind="resend", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="resend", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"resend"}))


class S3CompatibleKind(KindAccessor):
    kind = "s3-compatible"
    credentials = AuthAccessor(kind="s3-compatible", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"s3-compatible"}))


class SalesforceKind(KindAccessor):
    kind = "salesforce"
    oauth = AuthAccessor(kind="salesforce", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"salesforce"}))


class SlackKind(KindAccessor):
    kind = "slack"
    oauth = AuthAccessor(kind="slack", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="slack", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"slack"}))


class SlackPosthogCodeKind(KindAccessor):
    kind = "slack-posthog-code"
    oauth = AuthAccessor(kind="slack-posthog-code", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"slack-posthog-code"}))


class SnapchatKind(KindAccessor):
    kind = "snapchat"
    oauth = AuthAccessor(kind="snapchat", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"snapchat"}))


class SnowflakeKind(KindAccessor):
    kind = "snowflake"
    credentials = AuthAccessor(kind="snowflake", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"snowflake"}))


class StripeKind(KindAccessor):
    kind = "stripe"
    oauth = AuthAccessor(kind="stripe", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="stripe", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"stripe"}))


class TiktokAdsKind(KindAccessor):
    kind = "tiktok-ads"
    oauth = AuthAccessor(kind="tiktok-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"tiktok-ads"}))


class TwilioKind(KindAccessor):
    kind = "twilio"
    token = AuthAccessor(kind="twilio", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"twilio"}))


class TwitterAdsKind(KindAccessor):
    kind = "twitter-ads"
    oauth = AuthAccessor(kind="twitter-ads", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"twitter-ads"}))


class VercelKind(KindAccessor):
    kind = "vercel"
    oauth = AuthAccessor(kind="vercel", auth_type=AuthType.OAUTH)  # the default
    token = AuthAccessor(kind="vercel", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"vercel"}))


class YoutubeAnalyticsKind(KindAccessor):
    kind = "youtube-analytics"
    oauth = AuthAccessor(kind="youtube-analytics", auth_type=AuthType.OAUTH)  # the default
    any = IntegrationReader(kinds=frozenset({"youtube-analytics"}))


class GeneratedIntegrationManager(IntegrationManagerBase):
    anthropic = AnthropicKind()
    apns = ApnsKind()
    apple_ads = AppleAdsKind()
    aws_redshift = AwsRedshiftKind()
    aws_s3 = AwsS3Kind()
    azure_blob = AzureBlobKind()
    bing_ads = BingAdsKind()
    clickup = ClickupKind()
    customerio_app = CustomerioAppKind()
    customerio_track = CustomerioTrackKind()
    customerio_webhook = CustomerioWebhookKind()
    databricks = DatabricksKind()
    email = EmailKind()
    firebase = FirebaseKind()
    github = GithubKind()
    gitlab = GitlabKind()
    google_ads = GoogleAdsKind()
    google_analytics = GoogleAnalyticsKind()
    google_calendar = GoogleCalendarKind()
    google_cloud_service_account = GoogleCloudServiceAccountKind()
    google_cloud_storage = GoogleCloudStorageKind()
    google_pubsub = GooglePubsubKind()
    google_search_console = GoogleSearchConsoleKind()
    google_sheets = GoogleSheetsKind()
    helpscout = HelpscoutKind()
    hubspot = HubspotKind()
    instagram = InstagramKind()
    intercom = IntercomKind()
    jira = JiraKind()
    linear = LinearKind()
    linkedin_ads = LinkedinAdsKind()
    meta_ads = MetaAdsKind()
    pardot = PardotKind()
    pinterest_ads = PinterestAdsKind()
    postgresql = PostgresqlKind()
    posthog = PosthogKind()
    reddit_ads = RedditAdsKind()
    resend = ResendKind()
    s3_compatible = S3CompatibleKind()
    salesforce = SalesforceKind()
    slack = SlackKind()
    slack_posthog_code = SlackPosthogCodeKind()
    snapchat = SnapchatKind()
    snowflake = SnowflakeKind()
    stripe = StripeKind()
    tiktok_ads = TiktokAdsKind()
    twilio = TwilioKind()
    twitter_ads = TwitterAdsKind()
    vercel = VercelKind()
    youtube_analytics = YoutubeAnalyticsKind()
