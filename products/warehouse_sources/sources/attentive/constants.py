ATTENTIVE_API_ORIGIN = "https://api.attentivemobile.com"
ATTENTIVE_V1_BASE_URL = f"{ATTENTIVE_API_ORIGIN}/v1"

# Maps PostHog webhook-backed schema name -> Attentive webhook event `type`
# value. The webhook payload's top-level `type` field is matched against this
# map's values (via `webhook_resource_map` on the source) to route incoming
# events into the right warehouse table. Attentive's public REST API is
# write-oriented (no list-subscribers/messages/campaigns endpoints), so
# webhooks are the only extraction surface — there is no backfill path.
RESOURCE_TO_ATTENTIVE_EVENT_TYPE: dict[str, str] = {
    "sms_subscribed": "sms.subscribed",
    "sms_sent": "sms.sent",
    "sms_message_link_click": "sms.message_link_click",
    "email_subscribed": "email.subscribed",
    "email_unsubscribed": "email.unsubscribed",
    "email_opened": "email.opened",
    "email_message_link_click": "email.message_link_click",
    "custom_attribute_set": "custom_attribute.set",
}

ATTENTIVE_WEBHOOK_SCHEMA_NAMES: tuple[str, ...] = tuple(RESOURCE_TO_ATTENTIVE_EVENT_TYPE.keys())
