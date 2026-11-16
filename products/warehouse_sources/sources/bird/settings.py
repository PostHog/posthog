from dataclasses import field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

# Bird serves each organization from one region. The key prefix `bk_{region}_` names it, and a key
# works only against that region's host.
BASE_URL_TEMPLATE = "https://{region}.platform.bird.com"
DEFAULT_REGION = "us1"

# Documented maximum of `limit` on every cursor listing.
PAGE_SIZE = 100

# The daily stats endpoints reject a window longer than 365 days, counting both ends.
DAILY_STATS_WINDOW_DAYS = 365


@frozen
class BirdEndpointConfig:
    name: str
    path: str
    # Cursor listings take `limit` and `starting_after` and return `next_cursor`. The daily stats
    # endpoints return one page and reject both parameters, because Bird rejects any unknown query
    # parameter with a 422.
    paginated: bool = True
    # The daily stats endpoints need a `from`/`to` window, set at run time.
    daily_stats: bool = False
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A creation time that never changes. Endpoints whose creation time can be null are left unpartitioned.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The query parameter that filters on the incremental field, server side.
    incremental_param: Optional[str] = None


# Every Bird listing returns the newest rows first and takes no sort parameter. Message, broadcast and
# conversation rows change after creation (delivery status, counts), and their listings filter only on
# creation time, so they are full refresh only. Inbound email never changes after it arrives.
BIRD_ENDPOINTS: dict[str, BirdEndpointConfig] = {
    config.name: config
    for config in (
        BirdEndpointConfig(name="contacts", path="/v1/contacts", partition_key="created_at"),
        BirdEndpointConfig(name="contact_properties", path="/v1/contact-properties", partition_key="created_at"),
        BirdEndpointConfig(name="audiences", path="/v1/audiences", partition_key="created_at"),
        BirdEndpointConfig(name="email_messages", path="/v1/email/messages", partition_key="created_at"),
        BirdEndpointConfig(name="email_broadcasts", path="/v1/email/broadcasts", partition_key="created_at"),
        # Built-in system templates are listed too, and they have no creation time.
        BirdEndpointConfig(name="email_templates", path="/v1/email/templates"),
        BirdEndpointConfig(name="email_domains", path="/v1/email/domains", partition_key="created_at"),
        # A removed suppression disappears from the listing, so the table must be replaced on each sync.
        BirdEndpointConfig(name="email_suppressions", path="/v1/email/suppressions", partition_key="created_at"),
        # Bird keeps received email for 30 days, so only an incremental merge keeps the older rows.
        BirdEndpointConfig(
            name="email_inbound_messages",
            path="/v1/email/inbound-messages",
            partition_key="received_at",
            incremental_fields=[
                {
                    "label": "received_at",
                    "type": IncrementalFieldType.DateTime,
                    "field": "received_at",
                    "field_type": IncrementalFieldType.DateTime,
                }
            ],
            incremental_param="received_after",
        ),
        BirdEndpointConfig(
            name="email_daily_stats",
            path="/v1/email/stats/daily",
            paginated=False,
            daily_stats=True,
            primary_keys=["bucket"],
        ),
        # Bird keeps SMS messages for 30 days.
        BirdEndpointConfig(name="sms_messages", path="/v1/sms/messages", partition_key="created_at"),
        BirdEndpointConfig(name="sms_templates", path="/v1/sms/templates"),
        BirdEndpointConfig(
            name="sms_daily_stats",
            path="/v1/sms/stats/daily",
            paginated=False,
            daily_stats=True,
            primary_keys=["bucket"],
        ),
        BirdEndpointConfig(name="whatsapp_messages", path="/v1/whatsapp/messages", partition_key="created_at"),
        BirdEndpointConfig(
            name="whatsapp_conversations", path="/v1/whatsapp/conversations", partition_key="created_at"
        ),
        BirdEndpointConfig(name="whatsapp_templates", path="/v1/whatsapp/templates"),
        BirdEndpointConfig(
            name="whatsapp_daily_stats",
            path="/v1/whatsapp/stats/daily",
            paginated=False,
            daily_stats=True,
            primary_keys=["bucket"],
        ),
        BirdEndpointConfig(name="numbers", path="/v1/numbers"),
    )
}

ENDPOINTS = tuple(BIRD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BIRD_ENDPOINTS.items() if config.incremental_fields
}
