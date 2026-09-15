"""Whether a task run was started by a person or by an unattended automation.

Sandbox-volume metrics and their anomaly alerts read this. An unattended origin's volume
tracks queue depth, so one hour that drains a backlog reads as a product surge while both
kinds share a total. Every task analytics event carries the answer as ``unattended``, so a
metric filters one property instead of keeping its own list of origin values — a list that
silently admits the next automation origin someone adds.

The table is exhaustive over ``Task.OriginProduct``; ``test_origin_attribution.py`` fails
when a new origin is missing from it, so classifying it is part of adding it. Other origin
groupings in this package answer different questions — which tasks a team may see
(``visibility``), which OAuth app a sandbox mints under (``temporal.oauth``), whose name a
PR carries (``temporal.process_task.utils``) — so none of them substitutes for this one.

Values are literals rather than enum members to keep this module out of the ``models``
import cycle.

``temporal.oauth.is_interactive_signals_run`` answers the same question per run, and more
sharply, for the signals origins alone: it reads the run's ``ai_stage``, so it also splits
a person-started second run on a task the pipeline created. This table is deliberately
coarser — one answer per origin, for every origin, from a task alone.
"""

# True where a person drives the origin by hand: a button, a Slack message, a chat turn.
# False where it runs with nobody waiting: a schedule, a queue, a pipeline stage.
RUN_ATTENDED_BY_ORIGIN: dict[str, bool] = {
    "user_created": True,
    "slack": True,
    "hogdesk": True,
    "posthog_ai": True,
    "signals_chat": True,
    "onboarding": True,
    "error_tracking": True,
    "eval_clusters": True,
    "session_summaries": True,
    "experiments": True,
    "mcp_analytics": True,
    # The image builder is a conversation a person opens from the environment settings and
    # drives through chat turns, so it is person-started despite the machine-sounding name.
    "image_builder": True,
    # Both the Inbox report CTAs and the report pipeline's own research and implementation
    # runs carry this origin, so `internal` is what tells them apart.
    "signal_report": True,
    "signals_scout": False,
    "scout_suggestions": False,
    "review_hog": False,
    "support_reply": False,
    "support_queue": False,
    "task_analysis": False,
    "loop": False,
    "workflow": False,
}


def is_unattended_run(*, origin_product: str | None, internal: bool) -> bool:
    return internal or not RUN_ATTENDED_BY_ORIGIN.get(origin_product or "", False)
