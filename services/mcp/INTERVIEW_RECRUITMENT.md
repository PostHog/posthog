# Adding an interview to MCP recruitment

> [!CAUTION]
> Unsolicited elicitation interrupts users and can become advertising spam.
> Get explicit approval from a human MCP owner for the study, audience, copy, and frequency before enabling it.
> Read [AGENTS.md](AGENTS.md#unsolicited-elicitation-high-risk). Adding a variant does not bypass that policy.

## Use the existing flag

Use the shared `mcp-interview-recruitment` multivariate flag in the MCP server's analytics project.
Each variant is one interview campaign. The server uses the selected variant key as `campaign_id`
and reads that variant's JSON payload from the same flag evaluation.

1. Choose a stable variant key, such as `warehouse-research`. Keys must match `[a-z][a-z0-9_-]{0,63}`.
2. Add the variant and its JSON payload. Supply both `message` and an HTTPS `booking_url`.
3. Add release conditions using existing person/group properties or cohorts. Assign the desired variant to each condition explicitly.
4. Add an AND condition excluding the [shared recruitment exclusion cohort](https://us.posthog.com/project/2/cohorts/641799) (`type: "cohort"`, `key: "id"`, `operator: "not_in"`, `value: 641799`) to every release condition for every variant, including test audiences. Maintain excluded users and organizations in this cohort instead of adding individual entries to the flag.
5. Put higher-priority, more specific conditions first. Check people who match only your study, only another study, both, and neither. Also check that excluded people receive no variant, even when they match a campaign's audience. One evaluation selects one interview; overlapping audiences do not produce multiple dialogs.
6. Agree on rollout with the MCP owner before changing percentages or enabling the flag. Preserve the other studies' variants, payloads, release conditions, and cohort exclusions when editing it.

The shared flag is [in US project 2](https://us.posthog.com/project/2/feature_flags/962543).
Its release conditions are alternatives (OR), so each one must include the cohort exclusion.
A separate exclusion-only condition does not protect the other conditions.
Reuse cohort `641799` when adding campaigns or release conditions; do not create a separate exclusion list per campaign.

Example payload:

```json
{
  "message": "Help us understand your warehouse workflow. Book a 20-minute interview.",
  "booking_url": "https://example.com/research-booking",
  "min_completed_tool_calls": 3,
  "min_session_age_seconds": 120
}
```

Replace the example URL and copy with the approved study details. Missing or invalid copy/URL skips
that campaign; a new variant never inherits another study's booking URL. Omitted timing fields default
to three completed product calls and 120 seconds. Do not put targeting rules or a `campaign_id` in
the payload. Targeting belongs in release conditions; campaign identity comes from the variant key.
The server does not supply current-client metadata as feature-flag property overrides.

The original campaign key is `mcp-research`. Boolean `true` remains compatible with this original
campaign for local development and existing boolean configurations, but still requires an explicit valid payload.
There is no fallback invitation copy or booking URL for any flag value.

## Shared protections and reporting

All campaigns share the same per-user suppression record. Accepting a booking link or declining an
invitation stops further recruitment across campaigns. Canceling or abandoning an invitation starts
a shared seven-day cooldown. Adding or renaming a campaign must not reset these records.

The code also enforces URL elicitation capability, direct MCP surface eligibility, task exclusions,
conversation warmup, and atomic reservation against simultaneous invitations. Reuse this flow;
do not add another tool, dispatcher hook, independent recruitment flag, or suppression namespace.

The existing events carry `campaign_id` and `invitation_id`:

- `mcp interview invitation sent`: the server offers the invitation; client rendering is not confirmed.
- `mcp interview booking link opened`: the first GET of its tracked redirect, including possible link scanners.
- `mcp interview invitation responded`: `response` is `accept`, `decline`, or `cancel`.

Filter by `campaign_id` for your study's results. Count distinct people for reach and invitation IDs
for attempts. Redirects, responses, and suppression records retain the campaign selected when the
invitation was sent, even if the flag changes while the dialog is open. Continuations also require the
original resolved organization and project. Consumed continuations cannot run again; errors must not
encourage automatically repeating the original tool, because a write may already have succeeded. These events do not track
completed bookings.

## Code and checks

The implementation is [src/hono/interview-recruitment.ts](src/hono/interview-recruitment.ts).
The request resolver passes the evaluated flag value and payload into its configuration parser.
Adding an ordinary study requires flag configuration, not another code path.

For a localhost development server, supply an explicit payload alongside the existing flag override:

```sh
export NODE_ENV=development
export FEATURE_FLAG_OVERRIDES='{"mcp-interview-recruitment":"mcp-research"}'
export MCP_INTERVIEW_RECRUITMENT_PAYLOAD='{"message":"Synthetic interview invitation","booking_url":"https://example.com/book","min_completed_tool_calls":0,"min_session_age_seconds":0}'
```

Start or restart the local MCP server with those variables. This payload is accepted only for a localhost
API in `development` or `test`, with an explicit recruitment override. Production ignores it.
Missing, malformed, or incomplete payloads skip recruitment. The example disables warmup only for
local testing; production timing still comes from the flag payload. To verify event ingestion too,
configure the existing analytics API key and host for your local PostHog project.

For code changes, run the existing regression suites:

```sh
pnpm --filter=@posthog/mcp exec vitest run --config vitest.hono.config.mts tests/hono/interview-recruitment.test.ts tests/hono/request-state-resolver.test.ts
```
