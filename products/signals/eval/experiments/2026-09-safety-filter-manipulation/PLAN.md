# Safety-filter false-positive experiment — plan

## Question

The per-signal safety filter (`backend/temporal/safety_filter.py`) rejects too many legitimate signals. Find where it is wrong and fix the prompt and logic so it is wrong less, without changing the production model.

## Decisions fixed before running

- **Model stays `claude-sonnet-5`.** No model swap, no model comparison. The in-session judge/labeler runs on a stronger model; production does not change.
- **What the filter should block: manipulation of the agent only.** Not security topics, not the team's own risky changes. Human review of every resulting pull request, the report judge, and the agent's own rules are the downstream controls for risky-but-honest work. (A tiered "flag, don't block, needs human approval before autostart" layer for security-sensitive content is a possible follow-up, out of scope here.)
- **Addressing the agent is not manipulation on its own.** `AGENT BRIEF`, `OWNER DECISION`, `@bot review`, and app-authored error strings are normal in a self-driving workflow.

## Method

1. Recover original rejected-signal content from `posthog.ai_events` (30-day retention), joined from the safety stage's `$ai_generation` spans.
2. Label ~250 rejected signals plus accepted controls from original content, under the manipulation-only definition. Record the failure class for each false positive.
3. Build an invented attack set (`fixtures/attack_fixtures.jsonl`): manipulation cases across the five block categories, each paired with a near-miss safe control that shares topic, urgency, and imperative voice but carries no payload. Written from a property list; reserved domains, invented tokens; no customer content.
4. Replay the current prompt and the rewritten prompt over the same real signals and the same attack set on `claude-sonnet-5` at medium effort with the pipeline's request shape. Prompt is the only variable.
5. Iterate the prompt until it clears the labeled false positives, blocks every attack, and passes every control. Any attack leak found during iteration is a prompt bug to close, not a number to accept.

## Metrics

- **False positives (precision):** rejection rate on the labeled real signals and on the safe controls. Lower is better; accepted-signal over-block must stay at zero.
- **Recall floor:** fraction of the invented attacks blocked. Must be 19/19; a leak blocks the change.
- **Refusals / empty responses** counted separately, because the pipeline treats those as rejections.

## The change that ships

- `SIGNAL_SAFETY_LLM_MODEL` env var, default = `claude-sonnet-5` rather than the matching model, so a matching-model swap can no longer silently retune the gate; both safety stages resolve their model from it.
- One manipulation-only prompt for every source, replacing the two diverging prompts; source and current date injected in the user prompt.
- The report judge's prompt aligned to the same five-category definition. Its "0 rejections in ~59k reports" number was measured while the old filter removed the security-topic class before the judge saw it; replaying the newly admitted signals showed the old judge prompt rejected 20 of 33, and a judge rejection fails the whole report.
- Delimiter hardening in both stages: the closing tag is neutralized in code, and each prompt states that only the header lines are metadata. Two forgery fixtures added.
- Both prompts tell the model never to reproduce a secret value in the explanation, since the explanation is stored.

## Measurement after the change (separate, product-side)

- Judge scout reads original content from `ai_events` before grading, and samples accepted signals per run so recall is measured in production, not only in this offline eval.
- Dashboard 1999216 gains a rolling false-positive tile with a minimum-sample guard and a floor alert on daily blocks.

These are tracked with the rollout, not in this eval folder.
