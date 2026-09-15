---
name: finding-experiments
description: Resolves a PostHog experiment reference from natural language to a concrete experiment ID with `experiment-list` (not feature-flag tools), using its server-side search, status, creator, ordering, and pagination parameters, with disambiguation when multiple experiments match. Use when the user names or quotes an experiment ("split test demo", "the File engagement boost experiment", "onboarding retention test", "landing page hero experiment", "pricing experiment"), describes it loosely ("the signup experiment", "my pricing test", "the one with the new checkout"), uses a relative reference ("latest", "most recent", "the one I created yesterday"), filters by status (running, draft, paused, exposure frozen, stopped, complete) or by archived state, or otherwise refers to an experiment by anything other than its concrete ID.
---

# Finding experiments

Users refer to experiments by name, description, or relative references — not by ID.
This skill resolves natural language references to concrete experiment IDs.

## How to find an experiment

Use the **experiment-list** tool from the Posthog-local MCP server.

IMPORTANT: Do NOT use `feature-flag-get-all` or any feature flag tool to find
experiments. Use the dedicated experiment list tool: `experiment-list`.

Filter on the server.
A project can hold hundreds of experiments, and one response holds one page of 100.

- **By name**: `experiment-list {search: "<terms>"}`.
  Search matches the name only, case-insensitive, as a substring.
  It does NOT match the description.
  Search the distinctive words of the reference, not the whole phrase — "the signup experiment" becomes `search: "signup"`.
- **By description**: there is no server-side filter for this, because `search` does not read the description.
  When the reference describes the change rather than naming it — "the one with the new checkout" — page the list and compare the `description` field of each result yourself.
  Narrow the pages first with `status` or `archived` where the reference allows it.
- **By status**: `experiment-list {status: "<status>"}`.
  Values are `draft`, `running`, `paused`, `exposure_frozen`, `stopped`, `complete` (an alias for `stopped`), and `all`.
- **By archived state**: `archived` is a separate boolean, not a status.
  The default is non-archived only, so pass `archived: true` to reach archived experiments.
- **By recency**: results are newest first unless you pass `order`, so the first result answers "latest" or "most recent".
  Order by another allowlisted field when the reference needs it — for example `order: "-start_date"` for "the last one I launched".
  A descending date order lists the rows that carry no date first, so `-start_date` leads with drafts and `-end_date` with experiments still running.
  Take the first result that carries the date, and page on if a whole page carries none.
- **By creator**: `experiment-list {created_by_id: <user id>}`.
  "The one I created yesterday" needs this filter, because the default list holds every creator and the response carries no `created_by` field to check after the fact.
  Call `user-get {uuid: "@me"}` for the user's `id`, and ask which experiment they mean when you cannot resolve it.
- **By flag**: `experiment-list {feature_flag_id: <id>}` when you already have the flag ID.
  Otherwise match the `feature_flag_key` field of the results.

Combine the filters.
`{search: "checkout", status: "running"}` is one call, not two.

### Paginate before you say "no matches"

The response carries `count` and `next`.
If `next` is not null, more experiments match than you have seen.
Page with `offset` (`offset: 100`, `offset: 200`, ...) until `next` is null.

Only report no matches after a search that returned `count: 0`, or after a description scan that reached the last page.
A first page with no obvious match is not an answer.

## After finding matches

- **Exactly one match**: Use it. Confirm with the user by name before destructive actions (delete, ship, end).
- **Multiple matches**: List them with name, status, and creation date. Ask the user to pick.
- **No matches**: Retry with shorter or different search terms, then with `archived: true`.
  If the reference described the experiment rather than naming it, scan descriptions across every page before you give up.
  Tell the user only after those come back empty too.

## Get full details if needed

After resolving to an ID, call `experiment-get` for the full object (metrics, flag details, parameters).

## Examples

```text
User: "pause my signup experiment"

Agent:
1. Calls experiment-list {search: "signup", status: "running"}
2. One result: "New signup process" (ID: 1371, status: running)
3. Proceeds to pause experiment 1371
```

```text
User: "what happened to that old pricing test?"

Agent:
1. Calls experiment-list {search: "pricing"} — count 5, next null, so every match is in hand
2. Four are stopped and years old, far past page 1 of an unfiltered list
3. Lists them with name, status, and creation date, then asks the user which one
```

## When NOT to search

- You already have the experiment ID from earlier in the conversation
- The user just created the experiment — you have the ID from the create response
- The user provided the ID directly

## Related skills

- **`managing-experiment-lifecycle`** — act on the experiment once you've resolved its ID
- **`diagnosing-experiment-results`** — investigate the experiment you found
