"""Canonical, documentation-sourced descriptions for Twilio endpoints and columns.

Sourced from the official Twilio API reference (https://www.twilio.com/docs/usage/api). Keyed by the
endpoint names in `settings.py` `TWILIO_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Twilio table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Twilio resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "sid": "Unique 34-character identifier for the resource.",
    "account_sid": "SID of the account that owns the resource.",
    "date_created": "Time at which the resource was created (RFC 2822 format).",
    "date_updated": "Time at which the resource was last updated (RFC 2822 format).",
    "uri": "URI of the resource relative to the API base.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "messages": {
        "description": "An SMS, MMS, or WhatsApp message sent or received through Twilio.",
        "docs_url": "https://www.twilio.com/docs/sms/api/message-resource",
        "columns": _columns(
            **{"from": "Phone number or sender ID the message was sent from."},
            to="Phone number the message was sent to.",
            body="Text content of the message.",
            status="Status of the message (e.g. queued, sent, delivered, failed, received).",
            direction="Direction of the message (inbound, outbound-api, outbound-call, outbound-reply).",
            num_segments="Number of message segments used to deliver the message.",
            num_media="Number of media files attached to the message.",
            price="Amount charged for the message.",
            price_unit="Currency of the price, as an ISO 4217 code.",
            error_code="Error code if the message failed to send.",
            error_message="Human-readable description of the error, if any.",
            messaging_service_sid="SID of the messaging service used, if any.",
            date_sent="Time at which the message was sent (RFC 2822 format).",
        ),
    },
    "calls": {
        "description": "A phone call made or received through Twilio.",
        "docs_url": "https://www.twilio.com/docs/voice/api/call-resource",
        "columns": _columns(
            **{"from": "Phone number or client identifier that made the call."},
            to="Phone number or client identifier that received the call.",
            status="Status of the call (e.g. queued, ringing, in-progress, completed, busy, failed, no-answer).",
            direction="Direction of the call (inbound, outbound-api, outbound-dial).",
            duration="Length of the call in seconds.",
            price="Amount charged for the call.",
            price_unit="Currency of the price, as an ISO 4217 code.",
            start_time="Time at which the call started (RFC 2822 format).",
            end_time="Time at which the call ended (RFC 2822 format).",
            forwarded_from="Phone number the call was forwarded from, if applicable.",
            parent_call_sid="SID of the parent call, if this call was created by another call.",
        ),
    },
    "recordings": {
        "description": "An audio recording of a Twilio call or conference.",
        "docs_url": "https://www.twilio.com/docs/voice/api/recording",
        "columns": _columns(
            call_sid="SID of the call this recording was made from.",
            conference_sid="SID of the conference this recording was made from, if applicable.",
            status="Status of the recording (e.g. in-progress, completed, absent).",
            duration="Length of the recording in seconds.",
            channels="Number of channels in the recording (1 = mono, 2 = dual).",
            source="How the recording was created (e.g. DialVerb, Conference, StartCallRecordingAPI).",
            price="Amount charged for the recording.",
            price_unit="Currency of the price, as an ISO 4217 code.",
            start_time="Time at which the recording started (RFC 2822 format).",
        ),
    },
    "conferences": {
        "description": "A conference call hosting multiple Twilio call participants.",
        "docs_url": "https://www.twilio.com/docs/voice/api/conference-resource",
        "columns": _columns(
            friendly_name="User-provided name identifying the conference.",
            status="Status of the conference (e.g. init, in-progress, completed).",
            region="Region in which the conference is hosted.",
            reason_conference_ended="Reason the conference ended, if it has ended.",
            call_sid_ending_conference="SID of the call that ended the conference, if any.",
        ),
    },
    "addresses": {
        "description": "A geographic address registered on a Twilio account for regulatory compliance.",
        "docs_url": "https://www.twilio.com/docs/usage/api/address",
        "columns": _columns(
            friendly_name="User-provided name identifying the address.",
            customer_name="Name of the person or business associated with the address.",
            street="Street portion of the address.",
            city="City of the address.",
            region="State or region of the address.",
            postal_code="Postal code of the address.",
            iso_country="ISO 3166-1 alpha-2 country code of the address.",
            validated="Whether the address has been validated by Twilio.",
            verified="Whether the address has been verified for regulatory use.",
        ),
    },
    "applications": {
        "description": "A TwiML application that bundles a set of URLs for handling Twilio voice and messaging.",
        "docs_url": "https://www.twilio.com/docs/usage/api/applications",
        "columns": _columns(
            friendly_name="User-provided name identifying the application.",
            voice_url="URL Twilio requests when a call uses this application.",
            voice_method="HTTP method used to request the voice URL.",
            sms_url="URL Twilio requests when a message uses this application.",
            sms_method="HTTP method used to request the SMS URL.",
            status_callback="URL Twilio requests with status updates.",
        ),
    },
    "incoming_phone_numbers": {
        "description": "A phone number owned by your Twilio account and the handlers configured for it.",
        "docs_url": "https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource",
        "columns": _columns(
            friendly_name="User-provided name identifying the phone number.",
            phone_number="The phone number in E.164 format.",
            status="Status of the phone number.",
            voice_url="URL Twilio requests when this number receives a call.",
            sms_url="URL Twilio requests when this number receives a message.",
            capabilities="Capabilities of the number (voice, SMS, MMS, fax).",
            origin="How the number was provisioned (e.g. twilio, hosted).",
        ),
    },
    "keys": {
        "description": "An API key (SID and secret) used to authenticate requests to the Twilio API.",
        "docs_url": "https://www.twilio.com/docs/usage/api/keys",
        "columns": _columns(
            friendly_name="User-provided name identifying the API key.",
        ),
    },
    "outgoing_caller_ids": {
        "description": "A phone number verified for use as an outbound caller ID on the account.",
        "docs_url": "https://www.twilio.com/docs/voice/api/outgoing-caller-ids",
        "columns": _columns(
            friendly_name="User-provided name identifying the caller ID.",
            phone_number="The verified phone number in E.164 format.",
        ),
    },
    "queues": {
        "description": "A queue holding callers waiting to be connected to an agent.",
        "docs_url": "https://www.twilio.com/docs/voice/api/queue-resource",
        "columns": _columns(
            friendly_name="User-provided name identifying the queue.",
            current_size="Number of calls currently waiting in the queue.",
            max_size="Maximum number of calls the queue can hold.",
            average_wait_time="Average wait time of callers in the queue, in seconds.",
        ),
    },
    "transcriptions": {
        "description": "A text transcription of a Twilio call recording.",
        "docs_url": "https://www.twilio.com/docs/voice/api/recording-transcription",
        "columns": _columns(
            recording_sid="SID of the recording this transcription was generated from.",
            status="Status of the transcription (e.g. in-progress, completed, failed).",
            transcription_text="The transcribed text of the recording.",
            duration="Duration of the transcribed recording, in seconds.",
            price="Amount charged for the transcription.",
            price_unit="Currency of the price, as an ISO 4217 code.",
        ),
    },
}
