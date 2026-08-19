# GitHub source: per-endpoint load exposure

**Status: handoff. Written by an agent whose intermediate conclusions were wrong several times
(see "Errors made while producing this"). Every factual claim below carries a file reference or a
runnable command. Re-verify before acting; do not take the prose on trust.**

## The question this answers

The GitHub source exposes 54 endpoints. A customer connecting the source picks schemas from a
checkbox list, and 25 of the unenabled ones are pre-selected by default. The question is not which
tables _we_ want — it is **which of them will generate a large, repeating API load if somebody
turns them on against a big repository**, and which mechanism bounds that.

The webhook is one such mechanism. It is not the only one, and for most of the exposure here it is
irrelevant.

## Re-deriving the classification

The table below is generated, not hand-written. Paste this into `python3` from the repo root:

```python
import ast, pathlib
p = pathlib.Path("products/warehouse_sources/backend/temporal/data_imports/sources/github/settings.py")
tree = ast.parse(p.read_text())
eps = {}
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "GITHUB_ENDPOINTS":
        for k, v in zip(node.value.keys, node.value.values):
            kw = {x.arg: x.value for x in v.keywords}
            def lit(n, d=None):
                if n not in kw: return d
                try: return ast.literal_eval(kw[n])
                except Exception: return "<expr>"
            inc = kw.get("incremental_fields")
            eps[ast.literal_eval(k)] = dict(
                fanout=lit("fan_out_parent"),
                n_inc=len(inc.elts) if isinstance(inc, ast.List) else 0,
                since=lit("supports_since_param", False),
                lookback=lit("initial_lookback_days"),
                dflt=lit("should_sync_default", True),
            )
WEBHOOK = {"workflow_jobs","workflow_runs","reviews","deployments","deployment_statuses","check_runs"}
for n, e in sorted(eps.items()):
    wh_only = n in WEBHOOK and e["lookback"] == 0
    cls = ("guarded" if wh_only else
           "1-fanout-pollable" if e["fanout"] else
           "2-full-refresh" if e["n_inc"] == 0 else
           "3-bounded")
    print(f"{cls:18} {n:24} default_on={e['dflt']}")
```

`WEBHOOK` mirrors `GITHUB_WEBHOOK_RESOURCE_MAP` in `source.py`. If that map changes, update the set.

## The four classes

### Class 1 — fan-out with poll still selectable (3 endpoints)

Cost is **one API call per parent row, every sync**. This is the shape that scales with repo
activity rather than with the table's own size.

| Endpoint          | Fans out over | Guard today                                                                                                                                                                                                                                       |
| ----------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `check_runs`      | commits       | **none.** It is in `GITHUB_WEBHOOK_RESOURCE_MAP`, but `initial_lookback_days=7`, so `webhook_only` is False and `supports_poll` is True (`source.py`, `_schema_for_endpoint`). A user can select incremental poll and get the per-commit fan-out. |
| `commit_statuses` | commits       | none — not in the webhook map at all.                                                                                                                                                                                                             |
| `team_members`    | teams         | acceptable; a repo has few teams.                                                                                                                                                                                                                 |

`reviews`, `workflow_jobs` and `deployment_statuses` are the same fan-out shape and are already
guarded, by being webhook-only. **That flag is a load guard, not a freshness feature** — see the
comment above `webhook_only` in `_schema_for_endpoint`, which says it exists so users cannot pick a
poll mode that would misbehave.

`commit_statuses` has a second, independent problem: its fan-out bounds the parent walk on the
commit's immutable `created_at` and it sets no `fan_out_parent_recency_field`, so a status posted
against a commit _after_ the watermark has moved past it is never fetched. Enabling it on poll
therefore yields a table with permanent holes as well as the load. Compare `deployments`, which
does set that field.

### Class 2 — no incremental field at all (34 endpoints, 25 default-selected)

These have `incremental_fields=[]`, so every sync re-pulls the entire collection. **This is the
largest exposure in the source and a webhook does not address any of it.**

Large on a busy repo: `stargazers`, `subscribers`, `contributors`, `branches`, `tags`, `artifacts`,
`actions_caches`, `commit_comments`, `releases`, `labels`, `milestones`.

Order-of-magnitude for one of them: `PostHog/posthog` has roughly 28k stars, so `stargazers` at 100
rows per page is about 280 requests **on every sync, indefinitely**. It is `should_sync_default=True`.

The 9 that are already `should_sync_default=False`: `collaborators`, `hooks`, `repository_teams`,
`runners`, `teams`, and the four `traffic_*` endpoints.

### Class 3 — bounded (12 endpoints)

Either a server-side `since` filter or a watermark-bounded walk. Includes `pull_requests`,
`issues`, `issue_events`, `commits`, `forks`, `repository_activity`, the four alert/advisory
tables, and both comment tables.

`issue_comments` and `pull_request_comments` sit here: both set `supports_since_param=True`, so
steady state is bounded server-side and cheap. **Their only exposure is the first sync**, which has
no watermark and therefore walks all history. (Correction found during implementation: this doc
originally claimed `initial_lookback_days` already bounded that as a config-only change. It did
not; the field was consumed only by the fan-out parent cutoff and the `== 0` webhook-only
sentinel. `_build_initial_params` now also applies it as a first-sync `since` floor for
since-capable repo-wide endpoints, and both comment tables set it.) They do not need a webhook to
be safe.

### Class 4 — guarded (5 endpoints)

`reviews`, `workflow_jobs`, `deployment_statuses`, `workflow_runs`, `deployments`. All webhook-only
(`initial_lookback_days=0`), so poll is not selectable. The first three are fan-out shapes; the
last two are repo-wide but high enough volume that a full crawl was judged unaffordable.

Counts across the four classes: 3 + 34 + 12 + 5 = 54, the full endpoint set.

## How the webhook mechanism actually works

Verified in `github.py` (the dispatch lives in `github_source()`'s `items()` closure, roughly
lines 1414–1512) and `sources/common/webhook_s3.py`.

- **Webhook and poll are either/or, never both.** Once `webhook_enabled` is true the function
  returns webhook items _instead of_ the poll. There is no mode where both feeds run.
- `webhook_enabled` requires `schema.initial_sync_complete` **unless** the endpoint is webhook-only
  (`webhook_s3.py`, `webhook_enabled`). So for an endpoint that already polls, adding a map entry
  gives "poll bootstraps, then webhook takes over" with no extra configuration.
- **`webhook_only` is derived from `initial_lookback_days == 0`** in two places (`source.py`
  `_schema_for_endpoint`; `github.py` in the dispatch). The same field _also_ drives the fan-out
  first-sync floor in `_fan_out_get_rows`. One sentinel, three consumers — worth making explicit,
  though nothing here depends on that.
- **The only repair loop is `webhook_reconcile_lookback_days`**, and it is passed as
  `parent_cutoff_override`, which **only `_fan_out_get_rows` reads**. On a repo-wide endpoint it is
  silently ignored and the chained poll falls back to its watermark bound. So a reconcile heals
  dropped deliveries for fan-out endpoints only. Repo-wide endpoints cannot self-heal today.
- **Rollout needs no hook surgery.** Flipping a schema to `sync_type=WEBHOOK` goes through the
  schema-update view, which calls `reconcile_webhook_events` → `GithubSource.sync_webhook_events`.
  That PATCHes every repo hook to the full mapped event set; its docstring states it "auto-heals
  webhooks created before `GITHUB_WEBHOOK_RESOURCE_MAP` gained new events."
- **Adding an endpoint to the webhook** is: one map entry in `source.py`; a reshape branch in
  `webhook_template.py` _only if_ GitHub's nesting key differs from the event name; `version_keys`
  in `settings.py` for dedupe (the delta merge does not dedupe within a batch); tests.

Nesting keys, checked against GitHub's webhook payload docs: `pull_request` → `pull_request`
(matches, no reshape needed); `issues` → `issue`; `issue_comment` and
`pull_request_review_comment` → both `comment`; `status` → **fields at body top level, no nesting
key**; `check_run` → `check_run`.

## Current state of project 2's four GitHub sources

Read via the `external-data-sources-list` MCP tool. Only `eng_analytics` uses webhooks.

| Schema                                | ai_gateway   | eng_analytics | website      | (no prefix) |
| ------------------------------------- | ------------ | ------------- | ------------ | ----------- |
| `workflow_runs` / `workflow_jobs`     | ·            | webhook       | ·            | ·           |
| `reviews`                             | ·            | webhook       | ·            | ·           |
| `deployments` / `deployment_statuses` | ·            | webhook       | ·            | ·           |
| `pull_requests`                       | ·            | incremental   | incremental  | incremental |
| `issue_events`                        | ·            | incremental   | ·            | ·           |
| `issues`                              | full_refresh | full_refresh  | full_refresh | was on      |
| `commits`                             | ·            | ·             | incremental  | ·           |
| `teams` / `team_members`              | ·            | full_refresh  | ·            | ·           |

**43 endpoints have never been enabled in any of the four**, including all of `check_runs`,
`commit_statuses`, `issue_comments`, `pull_request_comments`.

Tracing where each _enabled_ endpoint came from (`git log -S'"<name>": GithubEndpointConfig'`),
every one arrived in a purpose-built PR except `issue_events`. Of the 38 tables added in bulk
by PR #73856, `issue_events` is the only one ever switched on.

## Open questions this did not resolve

- **Why is `issues` on `full_refresh` in all three sources that have it on**, when it shipped with
  `incremental_fields` from the original commit (#46336) and `pull_requests` — defined directly
  below it, same shape — is on incremental in the same sources? Three independent setups made the
  same choice, so it is a pattern rather than a slip. Could be the picker's default; could be a
  known problem with incremental there. Unknown. Also unexplained: the table holds 10,483 rows
  while `pull_requests` holds 63,652, even though GitHub's `/issues` endpoint returns PRs too.
- **Which class-2 endpoints can gain incremental support** from the GitHub API, and which are
  genuinely full-refresh-only. Not audited.
- **Whether `should_sync_default=True` on 25 full-refresh endpoints** is deliberate. The field's
  own comment frames it as a permissions concern ("tables needing grants beyond the repo scope"),
  not a load one, which suggests load was never the axis it was set on.

## Errors made while producing this

Listed so the next person does not inherit them from earlier drafts, commits, or chat logs.

1. **Claimed webhook and poll run together, with the poll as drift repair.** They are either/or.
2. **Claimed `webhook_reconcile_lookback_days` would heal dropped deliveries for the comment
   tables.** It does not; the override is fan-out-only.
3. **Claimed `pull_requests` re-walks all 63,652 rows every sync (~637 requests).** False. It sets
   `sort_mode="desc"`, so once a watermark exists `_resolve_sort_mode` returns desc, which sets
   `stop_cutoff` to the watermark. Only the first sync is unbounded.
4. **Claimed adding an event to the resource map is inert for existing sources and needs a manual
   hook resync.** False — `sync_webhook_events` auto-heals on the normal schema-enable path.
5. **Recommended simply toggling `check_runs` on as a free win.** It is `should_sync_default=False`
   for a reason: in poll mode it is a per-commit fan-out, i.e. exactly the hazard this document is
   about. It needs the webhook-only guard first.
6. **Framed the whole analysis around freshness for the engineering-analytics PR page** for most of
   its life, rather than around load exposure from customer-enabled schemas. The class-2 finding —
   the largest exposure — only surfaced once the framing was corrected.

## Proposed work, ranked

Direction decided 2026-08-19: favor extending webhook coverage over retrofitting incremental
polling. The Class-2 audit is parked as follow-up.

1. **Close the fan-out poll hole.** Set `initial_lookback_days=0` on `check_runs` so it becomes
   webhook-only and poll stops being selectable. Config only; kills the worst live per-commit
   fan-out hazard.
2. **`commit_statuses` to webhook-only.** Add it to `GITHUB_WEBHOOK_RESOURCE_MAP` (`status` event)
   with a reshape branch (the payload has no nesting key: build the row from top-level body fields,
   strip the `commit`/`repository`/`sender` envelope, inject `commit_sha := body.sha` to match what
   the fan-out injects), and set `initial_lookback_days=0`. No `version_keys` — statuses are
   append-only, and (correction found during implementation) nothing skips composite keys: the
   dedupe transformer is built whenever `version_keys` is set and collapses on the FIRST pk column
   only, so `version_keys` on the composite `["commit_sha", "id"]` key would collapse a commit's
   statuses to one row. Guarded by `test_no_composite_key_endpoint_declares_version_keys`. Side
   effect: fixes the dropped-late-status bug the poll has today.
3. **Webhook-feed the three comment tables.** Add `issue_comments` (`issue_comment`),
   `pull_request_comments` (`pull_request_review_comment`), and `commit_comments`
   (`commit_comment`) to the map; all three payloads nest the row under `comment`, so they need
   reshape branches like `pull_request_review` already has. Poll stays as bootstrap/fallback via the
   existing initial-sync-then-webhook mechanism. `commit_comments` is the biggest win — its poll can
   only ever be full refresh. The other two are `since`-bounded and cheap on the poll, so for them
   this is freshness and fewer calls, not safety. Their bootstrap is floored at
   `initial_lookback_days=14` through the first-sync `since` floor described in Class 3.
4. **Class-2 audit (parked).** Still the biggest raw exposure: ~25 default-selected endpoints
   re-pull their whole collection every sync. Decide per endpoint later: add incremental where the
   API allows, otherwise flip `should_sync_default=False`. Some (e.g. `stargazers`, `forks`,
   `releases`) have webhook events and could join the map instead.
5. **Leave `pull_requests` on the poll.** Bounded and self-healing; a repo-wide webhook cannot
   reconcile, so flipping it would trade a working poll for a permanently stale row in the table
   every engineering-analytics surface reads. Its webhook payload is also the full single-PR GET
   shape against the poll's list shape, which would drift columns.
