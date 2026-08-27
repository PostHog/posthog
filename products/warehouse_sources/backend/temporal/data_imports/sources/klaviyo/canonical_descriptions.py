"""Canonical, documentation-sourced descriptions for Klaviyo endpoints and columns.

Sourced from the official Klaviyo API reference (https://developers.klaviyo.com/en/reference/api_overview).
Keyed by the endpoint names in `settings.py` `KLAVIYO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Klaviyo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Klaviyo's JSON:API responses flatten the nested `attributes` object onto each row, so attribute
# fields (name, status, created, updated, ...) appear as top-level columns.
_CAMPAIGN_COLUMNS = {
    "id": "Unique identifier for the campaign.",
    "name": "The campaign's name.",
    "status": "Current status of the campaign (e.g. Draft, Queued without Recipients, Sent).",
    "archived": "Whether the campaign has been archived.",
    "channel": "The channel the campaign sends through (email or sms).",
    "audiences": "The lists and segments the campaign is sent to and excluded from.",
    "send_options": "Options controlling how the campaign is sent.",
    "tracking_options": "Tracking options for opens, clicks, and UTM parameters.",
    "send_strategy": "The strategy used to schedule and send the campaign.",
    "created_at": "Time at which the campaign was created.",
    "updated_at": "Time at which the campaign was last updated.",
    "scheduled_at": "Time at which the campaign is scheduled to send.",
    "send_time": "Time at which the campaign was sent.",
}

_CATALOG_SHARED_COLUMNS = {
    "external_id": "The ID of the record in the external system the catalog is fed from.",
    "title": "The title of the record.",
    "description": "A description of the record.",
    "price": "The price displayed for the record in feeds and blocks.",
    "url": "URL pointing to the location of the record on your website.",
    "image_full_url": "URL pointing to a full image of the record.",
    "image_thumbnail_url": "URL pointing to an image thumbnail of the record.",
    "images": "List of URLs pointing to images of the record.",
    "custom_metadata": "Flat JSON blob of custom metadata about the record.",
    "published": "Whether the record is published.",
    "created": "Date and time when the record was created.",
    "updated": "Date and time when the record was last updated.",
}

# Both values reports return the same statistics; only the grouping columns differ. Rate statistics
# come back as fractions between 0 and 1.
_VALUES_REPORT_STATISTIC_COLUMNS = {
    "timeframe_key": "The Klaviyo timeframe the statistics were computed over.",
    "conversion_metric_id": "ID of the metric conversion statistics were attributed to.",
    "send_channel": "The channel the message was sent through (email, sms, push-notification, or whatsapp).",
    "average_order_value": "Average value of the orders attributed to the message.",
    "bounce_rate": "Share of delivered attempts that bounced.",
    "bounced": "Number of messages that bounced.",
    "bounced_or_failed": "Number of messages that bounced or failed to send.",
    "bounced_or_failed_rate": "Share of messages that bounced or failed to send.",
    "click_rate": "Share of delivered messages that were clicked.",
    "click_to_open_rate": "Share of opened messages that were clicked.",
    "clicks": "Total number of clicks.",
    "clicks_unique": "Number of recipients who clicked at least once.",
    "conversion_rate": "Share of recipients who completed the conversion metric.",
    "conversion_uniques": "Number of recipients who completed the conversion metric.",
    "conversion_value": "Total value of the conversions attributed to the message.",
    "conversions": "Number of times the conversion metric was completed.",
    "delivered": "Number of messages delivered.",
    "delivery_rate": "Share of messages that were delivered.",
    "failed": "Number of messages that failed to send.",
    "failed_rate": "Share of messages that failed to send.",
    "message_segment_count_sum": "Total number of SMS segments the messages were split into.",
    "open_rate": "Share of delivered messages that were opened.",
    "opens": "Total number of opens.",
    "opens_unique": "Number of recipients who opened at least once.",
    "recipients": "Number of recipients the message was sent to.",
    "revenue_per_recipient": "Conversion value divided by the number of recipients.",
    "spam_complaint_rate": "Share of delivered messages marked as spam.",
    "spam_complaints": "Number of messages marked as spam.",
    "text_message_credit_usage_amount": "SMS credits consumed by the messages.",
    "text_message_roi": "Return on investment for the SMS spend.",
    "text_message_spend": "Amount spent sending the SMS messages.",
    "unsubscribe_rate": "Share of recipients who unsubscribed.",
    "unsubscribe_uniques": "Number of recipients who unsubscribed.",
    "unsubscribes": "Total number of unsubscribes.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "email_campaigns": {
        "description": "An email marketing campaign in Klaviyo sent to a target audience.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_campaigns",
        "columns": _CAMPAIGN_COLUMNS,
    },
    "sms_campaigns": {
        "description": "An SMS marketing campaign in Klaviyo sent to a target audience.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_campaigns",
        "columns": _CAMPAIGN_COLUMNS,
    },
    "events": {
        "description": "An event in Klaviyo recording a profile's action, such as a placed order or opened email.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_events",
        "columns": {
            "id": "Unique identifier for the event.",
            "datetime": "Time at which the event occurred.",
            "timestamp": "Unix timestamp at which the event occurred.",
            "event_properties": "Properties attached to the event.",
            "uuid": "Universally unique identifier for the event.",
            "metric": "The metric this event is an occurrence of (related resource).",
            "profile": "The profile that performed the event (related resource).",
        },
    },
    "flows": {
        "description": "An automated flow in Klaviyo that sends messages based on triggers and conditions.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_flows",
        "columns": {
            "id": "Unique identifier for the flow.",
            "name": "The flow's name.",
            "status": "Current status of the flow (e.g. draft, manual, live).",
            "archived": "Whether the flow has been archived.",
            "trigger_type": "The type of trigger that starts the flow.",
            "created": "Time at which the flow was created.",
            "updated": "Time at which the flow was last updated.",
        },
    },
    "lists": {
        "description": "A list of profiles in Klaviyo used to target campaigns and flows.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_lists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "opt_in_process": "The opt-in process for the list (single or double opt-in).",
            "created": "Time at which the list was created.",
            "updated": "Time at which the list was last updated.",
        },
    },
    "metrics": {
        "description": "A metric in Klaviyo that defines a type of tracked event (e.g. Placed Order, Opened Email).",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_metrics",
        "columns": {
            "id": "Unique identifier for the metric.",
            "name": "The metric's name.",
            "integration": "The integration that reports this metric.",
            "created": "Time at which the metric was created.",
            "updated": "Time at which the metric was last updated.",
        },
    },
    "profiles": {
        "description": (
            "A profile in Klaviyo representing a person you can message and track. Includes consent "
            "and suppression status per channel in the subscriptions column."
        ),
        "docs_url": "https://developers.klaviyo.com/en/reference/get_profiles",
        "columns": {
            "id": "Unique identifier for the profile.",
            "email": "The profile's email address.",
            "phone_number": "The profile's phone number.",
            "external_id": "The external identifier you assigned to the profile.",
            "first_name": "The profile's first name.",
            "last_name": "The profile's last name.",
            "organization": "The organization the profile is associated with.",
            "title": "The profile's job title.",
            "location": "The profile's location details.",
            "subscriptions": (
                "The profile's consent and suppression status per channel, stored as JSON and "
                "requested by default. `email.marketing` holds `consent`, "
                "`can_receive_email_marketing`, `suppression` (global suppressions as "
                "{reason, timestamp} entries, with reason one of HARD_BOUNCE, INVALID_EMAIL, "
                "SPAM_COMPLAINT, UNSUBSCRIBE, or USER_SUPPRESSED), and `list_suppressions` "
                "(per-list suppressions as {list_id, reason, timestamp} entries). `sms.marketing` "
                "and `sms.transactional` hold `consent`, `consent_timestamp`, and a `can_receive_*` "
                "flag, while `mobile_push.marketing` holds `consent` and `can_receive_push_marketing`. Use "
                "this column to export unsubscribe, suppression, and consent state, e.g. when "
                "migrating to another sending platform."
            ),
            "properties": (
                "Custom properties set on the profile. Subscription status lives here in the `$consent` array "
                "— the communication channels (`sms`, `email`, and/or `push`) the profile is currently "
                "consented to — not in list membership: a profile can belong to a list without being "
                "subscribed. `$consent_timestamp` records when the profile consented to receive communication, "
                "but it is not reliably cleared on unsubscribe, so use `$consent`, not `$consent_timestamp`, "
                "to tell who is currently subscribed."
            ),
            "created": "Time at which the profile was created.",
            "updated": "Time at which the profile was last updated.",
            "last_event_date": "Time of the profile's most recent event.",
        },
    },
    "list_profiles": {
        "description": (
            "A flat join table mapping which profiles belong to which Klaviyo list. Rows for profiles removed "
            "from a list are only pruned by a full refresh. List membership is not the same as subscription: "
            "a profile can be on a list without being subscribed to any channel. To tell which channels "
            "(`sms`, `email`, and/or `push`) a profile is actually subscribed to, check the `$consent` array "
            "in the profile's `properties` (in the `profiles` table). To tell which profiles are suppressed "
            "for a specific list, use the `profiles` table's `subscriptions` column: "
            "`email.marketing.list_suppressions` records {list_id, reason, timestamp} per suppression."
        ),
        "docs_url": "https://developers.klaviyo.com/en/reference/get_profiles_for_list",
        "columns": {
            "list_id": "Identifier of the list.",
            "profile_id": "Identifier of a profile that is a member of the list.",
            "joined_group_at": (
                "The datetime when the profile most recently joined the list. Updated if the profile re-joins. "
                "Joining a list does not mean the profile is subscribed: check the `$consent` array in the "
                "`profiles` table's `properties` for current subscription status. This timestamp often matches "
                "the profile's `$consent_timestamp`, but not always — do not treat them as interchangeable."
            ),
        },
    },
    "segments": {
        "description": "A segment in Klaviyo: a dynamic group of profiles that matches a set of conditions.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_segments",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "The segment's name.",
            "definition": "The condition groups that determine which profiles belong to the segment.",
            "is_active": "Whether the segment is active and being evaluated.",
            "is_processing": "Whether Klaviyo is currently recalculating the segment's membership.",
            "is_starred": "Whether the segment is starred in the Klaviyo UI.",
            "created": "Time at which the segment was created.",
            "updated": "Time at which the segment was last updated.",
        },
    },
    "segment_profiles": {
        "description": (
            "A flat join table mapping which profiles belong to which Klaviyo segment. Segment membership is "
            "recalculated by Klaviyo, so profiles that stop matching are only removed on a full refresh."
        ),
        "docs_url": "https://developers.klaviyo.com/en/reference/get_segment_profiles",
        "columns": {
            "segment_id": "Identifier of the segment.",
            "profile_id": "Identifier of a profile that is a member of the segment.",
            "joined_group_at": "The datetime when the profile most recently joined the segment.",
        },
    },
    "flow_actions": {
        "description": "A step in a Klaviyo flow, such as sending a message, waiting, or branching on a condition.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_flow_flow_actions",
        "columns": {
            "id": "Unique identifier for the flow action.",
            "flow_id": "Identifier of the flow this action belongs to.",
            "definition": (
                "The encoded definition of what the action does. Its `type` holds the action type and its "
                "`data` holds the action's configuration, including the action's status and, for send steps, "
                "the message."
            ),
            "created": "Time at which the action was created.",
            "updated": "Time at which the action was last updated.",
        },
    },
    "flow_messages": {
        "description": "A message sent by a Klaviyo flow step, holding the content the step delivers.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_flow_action_messages",
        "columns": {
            "id": "Unique identifier for the flow message.",
            "flow_action_id": "Identifier of the flow action that sends this message.",
            "flow_id": "Identifier of the flow the sending action belongs to.",
            "channel": "The channel the message is sent through (email, sms, or push-notification).",
            "definition": (
                "The encoded definition of the message, holding its name, subject line, sender details, "
                "template, and body."
            ),
            "created": "Time at which the message was created.",
            "updated": "Time at which the message was last updated.",
        },
    },
    "campaign_values_reports": {
        "description": (
            "Klaviyo's own computed performance statistics for each campaign message over the last 365 days. "
            "Replaced in full on every sync, so it is a snapshot rather than a history."
        ),
        "docs_url": "https://developers.klaviyo.com/en/reference/query_campaign_values",
        "columns": {
            "campaign_id": "Identifier of the campaign the statistics belong to.",
            "campaign_message_id": "Identifier of the campaign message the statistics belong to.",
            **_VALUES_REPORT_STATISTIC_COLUMNS,
        },
    },
    "flow_values_reports": {
        "description": (
            "Klaviyo's own computed performance statistics for each flow message over the last 365 days. "
            "Replaced in full on every sync, so it is a snapshot rather than a history."
        ),
        "docs_url": "https://developers.klaviyo.com/en/reference/query_flow_values",
        "columns": {
            "flow_id": "Identifier of the flow the statistics belong to.",
            "flow_message_id": "Identifier of the flow message the statistics belong to.",
            **_VALUES_REPORT_STATISTIC_COLUMNS,
        },
    },
    "templates": {
        "description": "A reusable email template in Klaviyo that campaigns and flow messages render from.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "The template's name.",
            "editor_type": (
                "Which editor built the template: SYSTEM_DRAGGABLE (drag and drop), SIMPLE (rich text), "
                "CODE (custom HTML), or USER_DRAGGABLE (custom HTML in the drag and drop editor)."
            ),
            "html": "The rendered HTML of the template.",
            "text": "The plain text version of the template.",
            "amp": "The AMP version of the template, when AMP email is enabled.",
            "definition": "The structured definition of the template body and styles.",
            "created": "Time at which the template was created.",
            "updated": "Time at which the template was last updated.",
        },
    },
    "forms": {
        "description": "A signup form in Klaviyo that collects profiles from your site.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_forms",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The form's name.",
            "status": "Current status of the form (e.g. draft, live).",
            "ab_test": "Whether the form is running an A/B test.",
            "created_at": "Time at which the form was created.",
            "updated_at": "Time at which the form was last updated.",
        },
    },
    "reviews": {
        "description": "A product review collected by Klaviyo Reviews.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_reviews",
        "columns": {
            "id": "Unique identifier for the review.",
            "email": "Email address of the reviewer.",
            "author": "Display name of the reviewer.",
            "title": "The review's title.",
            "content": "The body of the review.",
            "rating": "The star rating the reviewer gave, from 1 to 5.",
            "status": "Moderation status of the review, holding its `value` and any rejection reason.",
            "review_type": "Whether the review is about a product or the store overall.",
            "verified": "Whether the review comes from a verified buyer.",
            "images": "Images the reviewer attached.",
            "product": "The catalog product the review is about.",
            "public_reply": "The store's public reply to the review, if any.",
            "smart_quote": "A short highlighted excerpt Klaviyo picked out of the review.",
            "created": "Time at which the review was submitted.",
            "updated": "Time at which the review was last updated.",
        },
    },
    "catalog_items": {
        "description": "A product in your Klaviyo catalog, used for product feeds, blocks, and attribution.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_catalog_items",
        "columns": {"id": "Unique identifier for the catalog item.", **_CATALOG_SHARED_COLUMNS},
    },
    "catalog_variants": {
        "description": "A variant of a catalog item, such as a specific size or color.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_catalog_variants",
        "columns": {
            "id": "Unique identifier for the catalog variant.",
            "sku": "The SKU of the variant.",
            "inventory_policy": "Whether the variant stays visible in feeds and blocks when out of stock.",
            "inventory_quantity": "The quantity of the variant currently in stock.",
            **_CATALOG_SHARED_COLUMNS,
        },
    },
    "catalog_categories": {
        "description": "A category that groups catalog items together.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_catalog_categories",
        "columns": {
            "id": "Unique identifier for the catalog category.",
            "external_id": "The ID of the category in the external system the catalog is fed from.",
            "name": "The name of the category.",
            "updated": "Date and time when the category was last updated.",
        },
    },
    "coupons": {
        "description": "A coupon in Klaviyo that unique codes are issued from.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_coupons",
        "columns": {
            "id": "Unique identifier for the coupon.",
            "external_id": "The ID of the coupon in the ecommerce platform it came from.",
            "description": "A description of the coupon.",
            "monitor_configuration": "How Klaviyo monitors the coupon's code pool.",
        },
    },
    "coupon_codes": {
        "description": "A unique coupon code assigned to a profile.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_coupon_coupon_codes",
        "columns": {
            "id": "Unique identifier for the coupon code.",
            "coupon_id": "Identifier of the coupon this code was issued from.",
            "unique_code": "The code assigned to the profile.",
            "expires_at": "The datetime when the code expires.",
            "status": "Current status of the code (e.g. unassigned, assigned_to_profile, used).",
        },
    },
    "tags": {
        "description": "A tag used to organize Klaviyo campaigns, flows, lists, and segments.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
        },
    },
    "tag_groups": {
        "description": "A group that the tags in your account belong to.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_tag_groups",
        "columns": {
            "id": "Unique identifier for the tag group.",
            "name": "The tag group's name.",
            "exclusive": "Whether a resource can carry only one tag from this group.",
            "default": "Whether this is the account's default tag group.",
        },
    },
    "custom_metrics": {
        "description": "A custom metric in Klaviyo, defined by combining and filtering other metrics.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_custom_metrics",
        "columns": {
            "id": "Unique identifier for the custom metric.",
            "name": "The custom metric's name, unique across the account.",
            "definition": "The definition that computes the custom metric.",
            "created": "Time at which the custom metric was created.",
            "updated": "Time at which the custom metric was last updated.",
        },
    },
    "data_sources": {
        "description": "A source that feeds custom object data into Klaviyo.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_data_sources",
        "columns": {
            "id": "Unique identifier for the data source.",
            "title": "The data source's title.",
            "description": "A description of the data source.",
            "namespace": "The namespace the data source writes into.",
            "visibility": "The status of the data source.",
        },
    },
    "object_types": {
        "description": "A custom object type defined in Klaviyo, describing the shape of records you send it.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_object_types",
        "columns": {
            "id": "Unique identifier for the object type.",
            "title": "The object type's title.",
            "description": "A description of the object type.",
            "status": "The status of the schema associated with the object type.",
            "namespace": "The namespace the object type belongs to.",
            "created_at": "Time at which the object type was created.",
            "updated_at": "Time at which the object type was last updated.",
        },
    },
    "custom_object_records": {
        "description": "A single record of a custom object type, holding structured data synced into Klaviyo and linked to profiles.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_records_for_object_type",
        "columns": {
            "id": "Unique identifier for the record, in the form object_type_id:::record_id.",
            "object_type_id": "ID of the object type this record belongs to.",
            "record_properties": "The record's properties, as defined by the object type's schema.",
        },
    },
    "push_tokens": {
        "description": "A push notification token registered against a profile's device.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_push_tokens",
        "columns": {
            "id": "Unique identifier for the push token.",
            "token": "The push token itself.",
            "enablement_status": "Whether the device currently accepts push notifications.",
            "platform": "The device platform (ios or android).",
            "vendor": "The push vendor the token belongs to (APNs or FCM).",
            "background": "The background state of the token.",
            "recorded_date": "The date the token was recorded.",
            "metadata": "Device metadata Klaviyo captured with the token.",
            "created": "Time at which the token was created.",
        },
    },
    "images": {
        "description": "An image uploaded to your Klaviyo image library.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_images",
        "columns": {
            "id": "Unique identifier for the image.",
            "name": "The image's name.",
            "image_url": "URL the image is served from.",
            "format": "The image's file format.",
            "size": "The image's size in bytes.",
            "hidden": "Whether the image is hidden in the Klaviyo UI.",
            "updated_at": "Time at which the image was last updated.",
        },
    },
    "web_feeds": {
        "description": "A web feed Klaviyo fetches to render dynamic content in messages.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_web_feeds",
        "columns": {
            "id": "Unique identifier for the web feed.",
            "name": "The web feed's name.",
            "url": "The URL the feed is fetched from.",
            "request_method": "The HTTP method used to fetch the feed.",
            "content_type": "The content type of the feed.",
            "status": "The cache status of the feed.",
            "created": "Time at which the web feed was created.",
            "updated": "Time at which the web feed was last updated.",
        },
    },
    "webhooks": {
        "description": "A webhook Klaviyo posts events to. Requires Klaviyo's Advanced KDP add-on.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_webhooks",
        "columns": {
            "id": "Unique identifier for the webhook.",
            "name": "The webhook's name.",
            "description": "A description of the webhook.",
            "endpoint_url": "The URL Klaviyo posts to, truncated for security.",
            "enabled": "Whether the webhook is enabled.",
            "created_at": "Time at which the webhook was created.",
            "updated_at": "Time at which the webhook was last updated.",
        },
    },
    "accounts": {
        "description": "Your Klaviyo account's settings, including its timezone and preferred currency.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_accounts",
        "columns": {
            "id": "Unique identifier for the account, which is its public API key.",
            "test_account": "Whether the account is marked as a test account.",
            "contact_information": "The contact details shown in the footer of the account's messages.",
            "industry": "The kind of business the account is for.",
            "timezone": "The IANA timezone dates and times are displayed in.",
            "preferred_currency": "The currency used for the account's currency-based metrics.",
            "public_api_key": "The public API key used for client-side calls.",
            "locale": "The account's region and language.",
        },
    },
}
