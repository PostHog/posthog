"""Canonical dismiss / snooze reason codes for inbox signal reports.

Keep in sync with the inbox UI's `frontend/src/scenes/inbox/utils/dismissalReasons.ts`
(itself a port of the desktop `packages/shared/src/dismissal-reasons.ts`). Those lists are
the source of truth for the reason chips shown in the inbox. The `state` API validates a
caller-supplied `dismissal_reason` against this set so an agent can't invent a code that
would round-trip into the inbox as a raw, unlabelled chip.

`already_fixed` snoozes the report (restores it to the pipeline) rather than dismissing it,
mirroring `snoozesInsteadOfDismiss` on the frontend.
"""

# Ordered to match the frontend options. Value -> whether selecting it snoozes the report
# (restores to potential) instead of permanently dismissing (suppressing) it.
DISMISSAL_REASONS: dict[str, bool] = {
    "already_fixed": True,
    "report_unclear": False,
    "analysis_wrong": False,
    "wontfix_intentional": False,
    "wontfix_irrelevant": False,
    "other": False,
}

DISMISSAL_REASON_VALUES: list[str] = list(DISMISSAL_REASONS)
