"""Events a scout run writes into the team's *own* project.

Distinct from the `signals_scout_*` analytics events, which go to PostHog's internal project via
the `posthoganalytics` SDK. These land in the customer's event stream so a team can act on its
scouts with no PostHog-side wiring — insights, alerts, CDP destinations. The `$` prefix marks them
as PostHog-generated, keeping them out of a customer's own custom-event namespace.

A leaf module on purpose: anything that needs to reason about "which events did a scout produce?"
imports from here without dragging in the harness. The set is what the workflows product's
self-loop guard checks an event trigger against — a scout that can retrigger the workflow that ran
it is a loop, so the name list has to have exactly one home.
"""

from __future__ import annotations

CUSTOMER_REPORT_EMITTED_EVENT = "$scout_report_emitted"
CUSTOMER_REPORT_EDITED_EVENT = "$scout_report_edited"
CUSTOMER_STRUCTURED_OUTPUT_EVENT = "$scout_structured_output"

SCOUT_EMITTED_EVENTS: frozenset[str] = frozenset(
    {
        CUSTOMER_REPORT_EMITTED_EVENT,
        CUSTOMER_REPORT_EDITED_EVENT,
        CUSTOMER_STRUCTURED_OUTPUT_EVENT,
    }
)
