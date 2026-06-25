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
2. **Find the first deploy to the target environment after the merge.** Match the region the user asked about (`prod-us` for "the US", `prod-eu` for "the EU"). The annotations come back **newest-first**, so don't just take the first `... to <env>` match on page 1 — that's the _most recent_ deploy, not the first one after the merge. Walk newest→oldest (paginating with `offset`) through that environment's markers until a `date_marker` falls _before_ `mergedAt`; the last matching marker you saw before crossing that boundary is the first deploy after the merge.
3. **Confirm the deployed commit actually contains the merge commit.** A later `date_marker` is necessary but not sufficient — the deploy might predate the merge in git history. Verify ancestry:

   ```sh
   gh api repos/PostHog/posthog/compare/<merge_sha>...<deployed_sha> --jq '{status,ahead_by,behind_by}'
   ```

   `behind_by: 0` with `status` `ahead` or `identical` means the deployed commit includes the merge. If `behind_by > 0`, that deploy is _before_ the change — keep scanning forward to the next deploy of that environment.

4. **Report** the deploy time (and PR/commit) for the region asked about. Mention other regions if relevant — `prod-us` and `prod-eu` usually deploy minutes apart but not simultaneously.

## Notes

- "Live in the US" = `prod-us`; "the EU" = `prod-eu`. `dev` is the internal staging environment, not customer-facing.
- For a **query-runner / read-path** change, the new behaviour applies retroactively to all data once deployed — so you can't time it from event volume, only from the deploy annotation. For a **capture** change, event volume for the new property is a secondary cross-check, but the annotation is still the authoritative deploy time.
