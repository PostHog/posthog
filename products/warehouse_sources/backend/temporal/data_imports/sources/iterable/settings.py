from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class IterableEndpointConfig:
    name: str
    path: str
    data_key: str  # JSON key the result array is nested under in the response body
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)


@dataclass(frozen=True)
class IterableExportEndpointConfig:
    name: str
    data_type_name: str  # `dataTypeName` passed to `/api/export/data.json`
    # The timestamp `startDateTime`/`endDateTime` filter on: event time for events, last profile
    # update for users.
    cursor_field: str = "createdAt"
    # Event time never changes, so it is a stable partition key. `profileUpdatedAt` is not.
    partition_by_cursor: bool = True


# Iterable's list endpoints return their full result set in a single response wrapped under a
# named array (e.g. `{"campaigns": [...]}`). None of them expose a server-side timestamp filter
# (`startDateTime`/`updatedAt[after]`/etc.) we can verify, so every endpoint is full refresh —
# an "incremental" sync would still have to read every row each run.
ITERABLE_ENDPOINTS: dict[str, IterableEndpointConfig] = {
    "campaigns": IterableEndpointConfig(name="campaigns", path="/api/campaigns", data_key="campaigns"),
    "channels": IterableEndpointConfig(name="channels", path="/api/channels", data_key="channels"),
    "lists": IterableEndpointConfig(name="lists", path="/api/lists", data_key="lists"),
    "message_types": IterableEndpointConfig(name="message_types", path="/api/messageTypes", data_key="messageTypes"),
    "templates": IterableEndpointConfig(
        name="templates", path="/api/templates", data_key="templates", primary_key="templateId"
    ),
}

# Fan-out endpoints that return CSV / plain text rather than JSON, so they bypass the REST framework.
CAMPAIGN_METRICS = "campaign_metrics"
LIST_USERS = "list_users"

FAN_OUT_PRIMARY_KEYS: dict[str, list[str]] = {
    # One row per campaign with its lifetime metrics.
    CAMPAIGN_METRICS: ["id"],
    # A user can belong to many lists, so the list id is part of the key.
    LIST_USERS: ["listId", "email"],
}


def _export(name: str, data_type_name: str) -> IterableExportEndpointConfig:
    return IterableExportEndpointConfig(name=name, data_type_name=data_type_name)


# Every `dataTypeName` the Export API documents, except `unknownSession`.
ITERABLE_EXPORT_ENDPOINTS: dict[str, IterableExportEndpointConfig] = {
    config.name: config
    for config in [
        _export("email_send", "emailSend"),
        _export("email_open", "emailOpen"),
        _export("email_click", "emailClick"),
        _export("email_bounce", "emailBounce"),
        _export("email_complaint", "emailComplaint"),
        _export("email_send_skip", "emailSendSkip"),
        _export("email_subscribe", "emailSubscribe"),
        _export("email_unsubscribe", "emailUnSubscribe"),
        _export("hosted_unsubscribe_click", "hostedUnsubscribeClick"),
        _export("push_send", "pushSend"),
        _export("push_open", "pushOpen"),
        _export("push_uninstall", "pushUninstall"),
        _export("push_bounce", "pushBounce"),
        _export("push_send_skip", "pushSendSkip"),
        _export("in_app_send", "inAppSend"),
        _export("in_app_open", "inAppOpen"),
        _export("in_app_click", "inAppClick"),
        _export("in_app_close", "inAppClose"),
        _export("in_app_delete", "inAppDelete"),
        _export("in_app_delivery", "inAppDelivery"),
        _export("in_app_send_skip", "inAppSendSkip"),
        _export("in_app_recall", "inAppRecall"),
        _export("inbox_session", "inboxSession"),
        _export("inbox_message_impression", "inboxMessageImpression"),
        _export("sms_send", "smsSend"),
        _export("sms_bounce", "smsBounce"),
        _export("sms_click", "smsClick"),
        _export("sms_received", "smsReceived"),
        _export("sms_send_skip", "smsSendSkip"),
        _export("sms_usage_info", "smsUsageInfo"),
        _export("web_push_send", "webPushSend"),
        _export("web_push_click", "webPushClick"),
        _export("web_push_send_skip", "webPushSendSkip"),
        _export("embedded_send", "embeddedSend"),
        _export("embedded_send_skip", "embeddedSendSkip"),
        _export("embedded_click", "embeddedClick"),
        _export("embedded_received", "embeddedReceived"),
        _export("embedded_impression", "embeddedImpression"),
        _export("embedded_session", "embeddedSession"),
        _export("whatsapp_send", "whatsAppSend"),
        _export("whatsapp_send_skip", "whatsAppSendSkip"),
        _export("whatsapp_bounce", "whatsAppBounce"),
        _export("whatsapp_click", "whatsAppClick"),
        _export("whatsapp_received", "whatsAppReceived"),
        _export("whatsapp_seen", "whatsAppSeen"),
        _export("whatsapp_usage_info", "whatsAppUsageInfo"),
        _export("journey_exit", "journeyExit"),
        _export("purchase", "purchase"),
        _export("custom_event", "customEvent"),
        IterableExportEndpointConfig(
            name="users", data_type_name="user", cursor_field="profileUpdatedAt", partition_by_cursor=False
        ),
    ]
}

# First sync of an export table, and every full refresh, starts this far back. Iterable has no
# cheap way to find a project's earliest event, and walking back to its founding would spend the
# export rate limit on empty windows.
DEFAULT_EXPORT_LOOKBACK_DAYS = 365

ENDPOINTS = (
    *ITERABLE_ENDPOINTS.keys(),
    CAMPAIGN_METRICS,
    LIST_USERS,
    *ITERABLE_EXPORT_ENDPOINTS.keys(),
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: config.incremental_fields for name, config in ITERABLE_ENDPOINTS.items()},
    **{
        name: [
            {
                "label": config.cursor_field,
                "type": IncrementalFieldType.DateTime,
                "field": config.cursor_field,
                "field_type": IncrementalFieldType.DateTime,
            }
        ]
        for name, config in ITERABLE_EXPORT_ENDPOINTS.items()
    },
}

# Export rows carry no unique id to merge on, so the export tables append rather than merge.
APPEND_ONLY_ENDPOINTS = frozenset(ITERABLE_EXPORT_ENDPOINTS)

# All export tables share one per-project rate limit of a few requests a minute, so they start
# disabled and the user picks the ones they need.
SHOULD_SYNC_DEFAULT: dict[str, bool] = dict.fromkeys(ITERABLE_EXPORT_ENDPOINTS, False)
