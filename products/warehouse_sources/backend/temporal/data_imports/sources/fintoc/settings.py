from posthog.dataclasses import frozen

BASE_URL = "https://api.fintoc.com"
API_VERSION = "2026-02-01"


@frozen
class FintocEndpoint:
    path: str
    page_size_param: str = "limit"
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    requires_link_token: bool = False
    webhook_object: str | None = None
    webhook_events: tuple[str, ...] = ()


# Creation-date filters miss later status changes; timestamp filtering also needs live verification.
ENDPOINTS: dict[str, FintocEndpoint] = {
    "payment_intents": FintocEndpoint(
        path="/v2/payment_intents",
        webhook_object="payment_intent",
        webhook_events=tuple(
            f"payment_intent.{status}" for status in ("succeeded", "rejected", "failed", "pending", "expired")
        ),
    ),
    "transfers": FintocEndpoint(
        path="/v2/transfers",
        webhook_object="transfer",
        webhook_events=(
            "transfer.inbound.succeeded",
            "transfer.inbound.returned",
            "transfer.inbound.return_failed",
            "transfer.inbound.rejected",
            "transfer.inbound.reversed",
            "transfer.outbound.succeeded",
            "transfer.outbound.partially_succeeded",
            "transfer.outbound.failed",
            "transfer.outbound.returned",
            "transfer.outbound.reversed",
        ),
    ),
    "refunds": FintocEndpoint(
        path="/v1/refunds",
        page_size_param="per_page",
        webhook_object="refund",
        webhook_events=("refund.succeeded", "refund.failed", "refund.in_progress"),
    ),
    "charges": FintocEndpoint(
        path="/v1/charges",
        page_size_param="per_page",
        webhook_object="charge",
        webhook_events=("charge.succeeded", "charge.failed"),
    ),
    "checkout_sessions": FintocEndpoint(
        path="/v2/checkout_sessions",
        webhook_object="checkout_session",
        webhook_events=("checkout_session.finished", "checkout_session.expired"),
    ),
    "subscriptions": FintocEndpoint(path="/v2/subscriptions"),
    "invoices": FintocEndpoint(
        path="/v2/invoices",
        webhook_object="invoice",
        webhook_events=tuple(
            f"invoice.{status}"
            for status in (
                "created",
                "finalized",
                "paid",
                "payment_created",
                "payment_failed",
                "payment_succeeded",
                "voided",
            )
        ),
    ),
    "customers": FintocEndpoint(path="/v2/customers"),
    "links": FintocEndpoint(path="/v1/links", page_size_param="per_page"),
    "accounts": FintocEndpoint(
        path="/v1/accounts",
        page_size_param="per_page",
        partition_key=None,
        requires_link_token=True,
    ),
    "movements": FintocEndpoint(
        path="/v1/accounts/{account_id}/movements",
        page_size_param="per_page",
        primary_keys=("account_id", "id"),
        partition_key=None,
        requires_link_token=True,
    ),
}

AUTH_ERROR = "Your Fintoc API key or link token is invalid or expired. Check your credentials and reconnect."
PERMISSION_ERROR = "Your Fintoc API key cannot access this resource. Check your Fintoc product permissions."
LINK_TOKEN_ERROR = (
    "Add link tokens to import open-banking accounts and movements. Fintoc does not return tokens when listing links."
)
