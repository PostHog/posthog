# Slack follow-ups

A user in a Slack thread asks `@PostHog check this in two weeks and report back here`. The mention becomes a personal, one-time-triggered Loop bound to that thread; when it fires, a full agent run does the analysis with PostHog data access and its report lands as a reply in the same thread. If the data isn't mature yet, the run defers itself (capped) and posts a one-line note instead.

## The flow

1. **Scheduling.** `PostHogCodeSlackMentionWorkflow` runs the follow-up intent classifier (`posthog/temporal/ai/slack_app/activities/followups.py`) on fresh mentions, after thread collection and before the repository cascade, so a scheduling ask never spins up the repo-discovery sandbox. A detected ask calls `facade.loops.create_slack_followup_loop`, which creates the loop (visibility `personal`, `origin_product=slack`, no repository) with a one-time `run_at` trigger and the thread binding stored on `Loop.slack_thread_target`:

   ```json
   {
     "integration_id": 123,
     "slack_workspace_id": "T0123",
     "channel": "C0456",
     "thread_ts": "1722400000.000100",
     "requested_by_slack_user_id": "U0789",
     "max_defers": 3
   }
   ```

   The bot confirms in the thread, including the scheduled date and the cancel affordance.

2. **Firing.** The normal loop fire pipeline applies (`fire_loop`: owner eligibility, usage gate, dedup, rate caps, auto-pause). For a thread-bound loop, `_create_loop_task_and_run` additionally populates `pending_dispatch.slack_thread_context`, stamps Slack interaction state (the loop owner as actor), appends `SLACK_FOLLOWUP_BLOCK` to the prompt, and upserts the thread's `SlackThreadTaskMapping` to point at the new run. A mapping owned by a still-active run is left alone; that run's report then posts via the direct fallback in `dispatch_loop_run_terminal_notification`.

3. **Reporting.** The run's final message reaches the thread through the existing pending-reply relay (mapping lookup by `task_run`), exactly like a mention-created run's reply. After the report, thread replies route to the run via the existing follow-up forwarding, so the report is conversational.

4. **Self-defer.** When the data is too thin, the agent calls `POST .../tasks/{task_id}/runs/{run_id}/defer_followup/` (bounded 1 hour to 90 days out, one pending re-check at a time, capped by `slack_thread_target.max_defers`). The re-arm happens server-side in `logic/services/loop_followups.py` as a fresh one-time trigger, because loop-fired runs deliberately have `loop:write` stripped from their tokens. The endpoint is the sandbox's own REST channel (called with the run's key and ids), so its generated MCP tool entry (`tasks-runs-defer-followup-create`) stays disabled.

5. **Cancel.** `@PostHog cancel the follow-up` in the thread disables the requester's bound loops (`facade.loops.disable_slack_followup_loops_for_thread`, owner-only). Follow-up loops are also visible and manageable in the Loops UI.

## Rollout

The Slack surface sits behind the `slack-app-followups` flag (workspace + org keyed, see `products/slack_app/backend/feature_flags.py`), on top of the per-user `tasks` + `loops` access check. With the flag dark or the user lacking loops access, mentions behave exactly as before.

## Known limitations (v1)

- The thread snapshot in the loop's instructions is captured at scheduling time; messages posted after scheduling aren't re-read at fire time.
- Scheduling from a thread that already has an active task mapping routes the ask to the live agent as a normal message instead of scheduling.
- After the follow-up reports, cancelling via mention no longer applies (the thread routes to the run); use the Loops UI instead.
- Recurring "quiet watch" follow-ups (check on a cadence, only speak when there's something to say) are a planned follow-up milestone, not part of v1.
