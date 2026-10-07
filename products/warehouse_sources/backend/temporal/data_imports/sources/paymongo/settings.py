from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.paymongo.com/v1/"
PAGE_SIZE = 10
WEBHOOK_EVENTS = ("payment.paid", "payment.failed", "payment.refunded", "payment.refund.updated")


@frozen
class PaymongoEndpoint:
    path: str
    pagination: Literal["after", "payout", "single"] = "after"
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "created_at"


ENDPOINTS = {
    "payments": PaymongoEndpoint(path="payments"),
    "refunds": PaymongoEndpoint(path="refunds?data.attributes.payment_id={payment_id}"),
    "links": PaymongoEndpoint(path="payment_links", pagination="single"),
    "payouts": PaymongoEndpoint(path="payouts", pagination="payout"),
    "webhooks": PaymongoEndpoint(path="webhooks"),
}

# Creation-time filters cannot capture later refunds or status changes, and remain unverified.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
