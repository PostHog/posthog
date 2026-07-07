"""Canonical, documentation-sourced descriptions for Churnkey Data API endpoints and columns.

Sourced from the official Churnkey Data API reference (https://docs.churnkey.co/data-api).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Churnkey table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Sessions": {
        "description": "A single cancel-flow session: one customer's pass through Churnkey's cancellation flow, including the offers presented, what they accepted, and the eventual outcome.",
        "docs_url": "https://docs.churnkey.co/data-api",
        "columns": {
            "_id": "Unique identifier for the session.",
            "org": "Identifier of the Churnkey organization the session belongs to.",
            "blueprintId": "Identifier of the cancel-flow blueprint used for this session.",
            "segmentId": "Identifier of the customer segment matched for this session.",
            "abtest": "Identifier of the A/B test variant the session was bucketed into, if any.",
            "customer": "Nested object describing the customer (id, email, subscription, plan, billing interval, currency).",
            "acceptedOffer": "Nested object describing the offer the customer accepted (guid, offerType, pause interval/duration), if any.",
            "provider": "Billing provider associated with the customer's subscription (e.g. Stripe).",
            "aborted": "Whether the customer abandoned the flow before completing it.",
            "canceled": "Whether the subscription was ultimately canceled.",
            "surveyId": "Identifier of the cancellation survey presented.",
            "surveyChoiceId": "Identifier of the survey answer the customer selected.",
            "surveyChoiceValue": "Human-readable value of the selected survey answer.",
            "feedback": "Free-text feedback the customer left during the flow.",
            "discountCooldownApplied": "Whether a discount cooldown prevented re-offering a discount.",
            "customActionHandler": "Identifier of a custom action handler invoked during the flow, if any.",
            "presentedOffers": "Array of every offer presented in the session, each with its type, configuration, and accepted/declined timestamps.",
            "mode": "Mode the session ran in (e.g. live or test).",
            "createdAt": "Time at which the session was created.",
            "updatedAt": "Time at which the session was last updated.",
            "recordingStartTime": "Start time of the associated session recording, if any.",
            "recordingEndTime": "End time of the associated session recording, if any.",
        },
    },
}
