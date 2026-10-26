from dataclasses import field

from posthog.dataclasses import frozen

BASE_URL = "https://api.yotpo.com/"
REQUEST_TIMEOUT = (10, 30)


@frozen
class YotpoEndpoint:
    path: str
    data_selector: str
    description: str
    primary_keys: tuple[str, ...] | None = None
    partition_key: str | None = None
    page_size_param: str | None = None
    email_date_range: bool = False
    params: dict[str, str] = field(default_factory=dict)
    token_query_param: str | None = None


# Timestamp filters have not been verified with an account, so every table uses full refresh.
ENDPOINTS: dict[str, YotpoEndpoint] = {
    "reviews": YotpoEndpoint(
        path="v1/apps/{app_key}/reviews",
        data_selector="reviews",
        description="Product and site reviews, including unpublished reviews.",
        primary_keys=("id",),
        partition_key="created_at",
        page_size_param="count",
        params={"deleted": "true"},
    ),
    "email_analytics": YotpoEndpoint(
        path="analytics/v1/emails/{app_key}/emails_sent",
        data_selector="date_series_points",
        description="Daily counts of review request emails sent, grouped by email type, from the configured start date.",
        primary_keys=("since", "until"),
        partition_key="since",
        email_date_range=True,
        params={"date_bucket": "day", "group_by": "email_type"},
        token_query_param="token",
    ),
    "raw_data": YotpoEndpoint(
        path="analytics/v1/emails/{app_key}/export/raw_data",
        data_selector="records",
        description="Email delivery and engagement records from the configured start date.",
        # The API exposes no unique email delivery ID, so a guessed key could discard records.
        primary_keys=None,
        partition_key="email_sent_timestamp",
        page_size_param="per_page",
        email_date_range=True,
        # The docs name sort directions but do not define their parameter values.
    ),
    "unsubscribers": YotpoEndpoint(
        path="apps/{app_key}/unsubscribers",
        data_selector="response.unsubscribers",
        description="Email addresses excluded from Yotpo review request emails.",
        primary_keys=("user_email", "email_type_id"),
        page_size_param="count",
    ),
}
