---
name: checking-deploy-timing
description: 'Determine when a PostHog code change reached a given environment by reading the hidden GIT deploy annotations in the project and correlating them with the merge commit on GitHub. Use when PostHog staff ask "when was X deployed", "is my change live in the US/EU yet", "has my PR shipped", "did the fix roll out to prod-us", or otherwise want to know whether/when a commit, PR, or feature went out to a region. Do not answer deploy-timing questions from event/data volume alone — that only shows when data changed, not when code shipped.'
---

# Checking when something was deployed

PostHog's CI writes a deploy marker into the project as an **annotation** every time a commit
ships to an environment. These annotations are `hidden_in_user_interface: true`, so they don't
show in the UI and are easy to forget — but they are the source of truth for "when did this go
out". Always check them when staff ask about deploy timing, rather than inferring from when a
metric or event volume changed (that conflates a capture change with a query/code change).

## The deploy annotations

List them with `posthog:annotations-list` using `{"search": "deploy"}`. Each deploy marker looks like:

- `content`: `Deployed PostHog/posthog@<sha> to <env>` — env is `prod-us`, `prod-eu`, or `dev`
- `creation_type`: `GIT`
- `scope`: `organization`
- `hidden_in_user_interface`: `true`
- `date_marker`: the deploy time (UTC)

They're returned newest-first; paginate with `offset` if you need to go further back.

## Workflow

1. **Find the change's merge commit.** Identify the PR (e.g. `gh search prs --repo PostHog/posthog --author <user> "<keywords>"`), then `gh pr view <n> --repo PostHog/posthog --json number,title,mergedAt,mergeCommit,state`. Note the merge commit SHA and `mergedAt`.
2. **List the target environment's deploys around the merge, oldest-first.** Match the region the user asked about (`prod-us` for "the US", `prod-eu` for "the EU"). The annotations come back **newest-first**, so don't just take the first `... to <env>` match on page 1 — that's the _most recent_ deploy. Paginate (with `offset`) until you reach markers around `mergedAt`, then consider that environment's deploys in chronological order, starting with the first whose `date_marker` is _after_ `mergedAt`. Check them earliest-first in step 3.
3. **Confirm the deployed commit actually contains the merge commit.** A later `date_marker` is necessary but not sufficient — a deploy can fire just after the merge yet build a slightly older commit. Verify ancestry:

   ```sh
   gh api repos/PostHog/posthog/compare/<merge_sha>...<deployed_sha> --jq '{status,ahead_by,behind_by}'
   ```

   `behind_by: 0` with `status` `ahead` or `identical` means the deployed commit includes the merge — that's your answer. If `behind_by > 0`, this deploy predates the change; move to the **next newer** deploy of that environment (the next one chronologically) and re-check. The first deploy that passes is the one that shipped the change.

4. **Report** the deploy time (and PR/commit) for the region asked about. Mention other regions if relevant — `prod-us` and `prod-eu` usually deploy minutes apart but not simultaneously.

## Notes

- "Live in the US" = `prod-us`; "the EU" = `prod-eu`. `dev` is the internal staging environment, not customer-facing.
- For a **query-runner / read-path** change, the new behaviour applies retroactively to all data once deployed — so you can't time it from event volume, only from the deploy annotation. For a **capture** change, event volume for the new property is a secondary cross-check, but the annotation is still the authoritative deploy time.
