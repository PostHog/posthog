# Reviewer-quality run — `C-gpt55-xhigh-2`

- **Dumped:** 2026-07-24T01:35:44+00:00
- **Report id:** `019f9175-4420-7da6-9d5d-f7a00484ce0c` · **PR:** https://github.com/PostHog/posthog/pull/72680
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 5143s (85.7 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 14         | 10          | 2                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in       | cache write | cache read     | output      | >200K gens | true $     | gw $       |
| --------------- | --------------------------- | ------- | -------------- | ----------- | -------------- | ----------- | ---------- | ---------- | ---------- |
| gpt-5.5         | review                      | 220     | 15,166,343     | 0           | 0              | 83,677      | 0          | —          | $19.40     |
| claude-opus-4-8 | validation                  | 95      | 68,498         | 569,386     | 10,251,436     | 109,522     | 0          | $11.76     | $11.76     |
| gpt-5.5         | blind-spot                  | 62      | 4,676,254      | 0           | 0              | 25,223      | 0          | —          | $4.86      |
| claude-sonnet-5 | dedup                       | 1       | 11,100         | 0           | 0              | 1,717       | 0          | $0.04      | $0.04      |
| claude-sonnet-5 | other:perspective_selection | 1       | 9,029          | 0           | 0              | 1,347       | 0          | $0.03      | $0.03      |
| **total**       |                             | **379** | **19,931,224** | **569,386** | **10,251,436** | **221,486** | **0**      | **$11.84** | **$36.10** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.5` (282 gen(s), gw $24.27).
- naive method (all prompt tokens at input price): $57.26 — 4.8× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $30.0656 over 379 gen(s) (true $9.0671, Δ +231.6%)
  - · of which cache read: $13.8162 over 355 gen(s) (true $5.1257, Δ +169.5%)
  - · of which cache write: $3.5587 over 95 gen(s) (true $3.5587, Δ +0.0%)
  - · of which fresh (derived): $12.6908 over 379 gen(s) (true $0.3827, Δ +3215.7%)
  - output: $6.0357 over 379 gen(s) (true $2.7687, Δ +118.0%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …c2c2e871 | issues-review-p1-c3 | 00:11:27  | 0             | 0              | gpt-5.5         |
| …2f08f65b | issues-review-p1-c2 | 00:11:30  | 0             | 0              | gpt-5.5         |
| …ca16feaa | issues-review-p2-c1 | 00:11:31  | 0             | 0              | gpt-5.5         |
| …6d48f10e | issues-review-p1-c1 | 00:11:34  | 0             | 0              | gpt-5.5         |
| …10d422d1 | issues-review-p2-c2 | 00:11:34  | 0             | 0              | gpt-5.5         |
| …459a594f | issues-review-p3-c1 | 00:11:35  | 0             | 0              | gpt-5.5         |
| …fff06a85 | issues-review-p3-c2 | 00:11:36  | 0             | 0              | gpt-5.5         |
| …539614a9 | issues-review-p2-c3 | 00:11:51  | 0             | 0              | gpt-5.5         |
| …d642de68 | issues-review-p1-c2 | 00:41:28  | 0             | 0              | gpt-5.5         |
| …3ecc2cc1 | issues-review-p2-c3 | 00:41:29  | 0             | 0              | gpt-5.5         |
| …7e3c03d1 | issues-review-p1-c3 | 00:41:29  | 0             | 0              | gpt-5.5         |
| …f003d7e2 | issues-review-p2-c1 | 00:41:29  | 0             | 0              | gpt-5.5         |
| …f1ab0919 | issues-review-p1-c1 | 00:41:29  | 0             | 0              | gpt-5.5         |
| …73ee600a | issues-review-p3-c2 | 00:41:30  | 0             | 0              | gpt-5.5         |
| …3aea3e9c | issues-review-p2-c2 | 00:41:31  | 0             | 0              | gpt-5.5         |
| …ada829a3 | issues-review-p3-c1 | 00:41:32  | 0             | 0              | gpt-5.5         |
| …61fb57eb | issues-review-p1-c2 | 01:11:50  | 0             | 0              | gpt-5.5         |
| …a7e30ef1 | issues-review-p2-c2 | 01:11:51  | 0             | 0              | gpt-5.5         |
| …e2904cf2 | issues-review-p2-c1 | 01:11:51  | 0             | 0              | gpt-5.5         |
| …09328549 | issues-review-p3-c2 | 01:11:51  | 0             | 0              | gpt-5.5         |
| …af03869d | issues-review-p1-c1 | 01:11:52  | 0             | 0              | gpt-5.5         |
| …4f6a9db7 | issues-review-p3-c1 | 01:11:52  | 0             | 0              | gpt-5.5         |
| …d7cd9e98 | blind-spots-c1      | 01:15:54  | 0             | 0              | gpt-5.5         |
| …4bc6dff4 | blind-spots-c3      | 01:15:58  | 0             | 0              | gpt-5.5         |
| …55a2c03d | blind-spots-c2      | 01:16:02  | 0             | 0              | gpt-5.5         |
| …f340858f | blind-spots-c4      | 01:16:07  | 0             | 0              | gpt-5.5         |
| …e8680eaa | validation-c3       | 01:20:31  | 0             | 38,984         | claude-opus-4-8 |
| …c551de7f | validation-c1       | 01:20:34  | 0             | 39,374         | claude-opus-4-8 |
| …62c5aa5d | validation-c2       | 01:20:37  | 17,141        | 22,941         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **1/29** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 17s      |
| review wave (perspectives)  | 64m 40s  |
| blind-spot sweep            | 4m 21s   |
| dedup (incl. combine/clean) | 17s      |
| validation                  | 15m 23s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 69m 01s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | review-hog-perspective-contracts-security      | 1          |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 3     | review-hog-perspective-contracts-security      | 2          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | review-hog-blind-spots-general                 | 1          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix — products/review_hog/backend/api/settings.py:16-16,52-54,222-222

**Declare the new ReviewHog to Stamphog product dependency**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This chunk adds imports from `products.stamphog.backend.facade.*` in ReviewHog, but `tach.toml` currently does not list `products.stamphog` in the `products.review_hog` module's `depends_on`. Even though these imports use Stamphog's exposed facade, the product dependency itself still has to be declared; otherwise the architecture/dependency check will reject the new cross-product edge.
- **Suggestion:** Add `products.stamphog` to the `depends_on` list for `products.review_hog` in `tach.toml` if this dependency is intentional. If ReviewHog should not depend on Stamphog directly, move the connection check and hook registration behind an existing allowed boundary instead.
- **Validator:** - **Checked:** Whether the PR actually leaves `products.review_hog`'s `depends_on` without `products.stamphog`. The reviewer only saw the `settings.py` chunk (chunk 1); I pulled the full PR diff (`gh pr diff 72680`) to see every file it touches, including `tach.toml`.
- **Found:** The PR's own `tach.toml` diff adds the exact entry the finding says is missing — inside the `products.review_hog` module block: `+    # Facade-only (enforced by stamphog's [[interfaces]] block) ...` `+    "products.stamphog",` (tach.toml, review_hog `depends_on`). So the premise "tach.toml currently does not list products.stamphog" is mistaken for the merged state.
- **Found:** All three production `review_hog → stamphog` imports go through the exposed facade surface: `products/review_hog/backend/api/settings.py` imports `products.stamphog.backend.facade.api.has_reviewable_repo_config`; `products/review_hog/backend/receivers.py` imports `products.stamphog.backend.facade.inbox_hooks.register_inbox_acting_reviewer_resolver` and `products.stamphog.backend.facade.api.queue_inbox_pr_review`. Stamphog's existing `[[interfaces]]` block (tach.toml:1101-1108) exposes `backend\.facade.*`, so the interface check also passes. The only non-facade stamphog import in review_hog (`from products.stamphog.backend.models import StamphogRepoConfig`) is in `test_settings_api.py`, and `tests` is excluded in tach.toml's top-level `exclude`.
- **Impact:** Both `tach check --dependencies` and `--interfaces` are satisfied by the PR as written (consistent with the PR body stating that command was run). The suggested fix — add `products.stamphog` to `review_hog`'s `depends_on` — is already done in the diff, so the finding is wrong/unreproducible against the actual change and would be pure noise if surfaced.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:316-321

**Self-driving flag accepts any truthy context value**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The hosted context flag controls a security-sensitive carve-out that relaxes the bot-author and draft gates, but it is parsed with `bool(context.get("self_driving_review"))`. That treats non-empty strings like `"false"`, `"0"`, or any non-empty object as enabled. If the context producer ever serializes this as a string, or a malformed context reaches this entrypoint, the engine will grant the carve-out instead of failing closed.
- **Suggestion:** Require an explicit JSON boolean true before enabling the carve-out, for example `self_driving = context.get("self_driving_review") is True`, and consider rejecting/logging non-boolean values so contract drift is visible. Add a regression test with `self_driving_review: "false"` that still refuses a bot-authored draft.
- **Validator:** - **Checked:** The single producer of the `--context` JSON that `review_local.py::run` consumes: `build_reviewer_invocation` (products/stamphog/backend/logic/reviewer.py:98) and its only caller `run_review_in_sandbox` (products/stamphog/backend/temporal/activities.py:428–445), plus how the payload is serialized and re-parsed.
- **Found:** The value is a genuine `bool` at every hop. activities.py:445 passes `self_driving_review=bool(output.get("inbox_review"))` (already coerced); reviewer.py:98 types the parameter `self_driving_review: bool = False` and puts it in the `context` dict; reviewer.py:130 serializes with `json.dumps(context, ...)` → JSON `true`/`false`; review_local.py:391 reads it back via `json.loads` → a Python `bool`; only then does review_local.py:316 apply `bool(...)`. A JSON boolean round-trips losslessly, so at the flagged line the value is provably `True`, `False`, or absent (`bool(None)` → `False`, i.e. fails closed).
- **Found:** The finding is self-describedly hypothetical — "_if_ the context producer _ever_ serializes this as a string, or a malformed context reaches this entrypoint." There is exactly one producer (grep for `build_reviewer_invocation` / `--context` shows a single non-test call site) and it is server-assembled; the PR head cannot write the context file (the server holds the token and overwrites trusted paths), so there is no attacker-controllable or string-typed path to this key.
- **Impact:** The string-`"false"` carve-out grant cannot occur given the typed, `bool()`-coerced producer and the JSON round-trip. Switching to `is True` guards a condition the upstream types already rule out — the criteria's "speculative what-if" and "defensive-coding paranoia" drop categories. No concrete trigger can be named against the real code, so precision-over-recall says drop.

### [❌ dismissed] should_fix — products/review_hog/backend/receivers.py:144-154

**Webhook re-review can switch acting reviewers after Inbox assignments change**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The new Stamphog webhook resolver recomputes the acting reviewer from the report's latest suggested_reviewers artefact on every later push. Those artefacts are append-only/latest-wins and can be edited after the PR was originally opened, so a self-driving PR's later Stamphog reviews can become governed by a different user's toggle than the one resolved by the initial TaskRun receiver. That breaks the intended per-user gate: the original acting reviewer can opt out mid-PR, but a later assignment change to another opted-in reviewer would allow reviews to continue; the inverse can also stop reviews even though the original actor remains opted in.
- **Suggestion:** Make the webhook leg re-check the toggle for the same acting reviewer chosen by the initial receiver. Persist that acting_user_id with the self-driving PR provenance, or expose a stable acting_user_id through the tasks/Stamphog facade, then have resolve_stamphog_acting_reviewer load that user's ReviewUserSettings directly. If no stable actor is available for an old/incomplete run, fail closed rather than recomputing from the current suggested_reviewers set.
- **Validator:** - **Checked:** How `resolve_stamphog_acting_reviewer` (products/review*hog/backend/receivers.py:~217) and the webhook carve-out (`_inbox_rereview_carve_out`, products/stamphog/backend/tasks/tasks.py) resolve the reviewer; how the \_initial* receiver leg resolves it; whether `suggested_reviewers` artefacts can change post-PR-open; and what `acting_user_id` is actually used for.
- **Found:** Both legs call the identical `_resolve_assigned_reviewer(team_id, signal_report_id, task.created_by_id)` — the webhook leg passes the stable `run.task_created_by_id` and re-derives the reviewer set from the latest artefact, exactly as the receiver leg does. The receiver leg is NOT a one-time pin: `handle_task_run_saved` fires on _every_ TaskRun output save (every agent turn) and re-resolves each time. So there is no fixed "initial acting reviewer" for the webhook leg to diverge from — the whole system is latest-wins by construction.
- **Found:** This is the explicitly documented contract, not an oversight. `_resolve_assigned_reviewer`'s docstring defines assignment as "the report's **latest** `suggested_reviewers` artefact — the exact set the Inbox 'For you' filter matches and Slack notifications fan out to," and the new AGENTS.md invariant states the webhook leg deliberately "re-check[s] the toggle through the resolver." Assignment follows the current artefact everywhere in the product; the carve-out mirrors ReviewHog's own inbox-trigger semantics on purpose (PR decision 6).
- **Found:** No safety impact. The stale-approval dismissal is unconditional and never preference-gated (tasks.py skip path retracts on any head change regardless of toggle/assignee; documented + code-confirmed). And `acting_user_id` feeds only the toggle gate + a provenance/attribution stamp (`output.inbox_review`, engine `self_driving` flag) — stamphog posts via the team's GitHub App machine user, so a reviewer switch causes no impersonation.
- **Impact:** The reviewer's premise — that this "breaks the intended per-user gate" — is mistaken: the intended gate IS the _current_ assignee's toggle, consistent across both legs and the Inbox surfaces, so following an assignment change is the contract, not a break. The only observable effect is whether an advisory review verdict is produced for whoever is now assigned, under a narrow scenario (a human edits `suggested_reviewers` via the artefact API after the draft PR is already open, to a different opted-in/out member, while pushes continue). No correctness, data-loss, or security consequence. Per precision-over-recall this is a drop; the suggested fix (pin acting_user_id + fail-closed for old runs) would itself diverge from the documented latest-wins model and add defensive handling the design intentionally omits.

### [❌ dismissed] should_fix — products/review_hog/backend/receivers.py:114-138

**Stamphog enqueue is blocked behind the ReviewHog Temporal start**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** When both inbox toggles are enabled, the code registers the ReviewHog `on_commit` callback first and the Stamphog callback second. Django executes `on_commit` callbacks serially in registration order, and `_start_review` synchronously connects to Temporal before returning. If the ReviewHog Temporal start is slow or hung during an outage, the independent Stamphog review may be delayed or never queued even though its own toggle was enabled.
- **Suggestion:** Make the two dispatches operationally independent. The smallest change is to register the Stamphog `on_commit` callback before the ReviewHog callback, or use one `on_commit` callback that queues Stamphog first and then starts ReviewHog. A more robust option is to put both trigger requests behind durable async queue/outbox records so one backend's outage cannot block the other trigger.
- **Validator:** - **Checked:** `_start_review` (products/review_hog/backend/receivers.py:164-200), `_start_stamphog_review` (PR diff), the two `on_commit` registrations, and Django's serial on_commit execution model, plus the Temporal entry point `start_review_pr_workflow` (temporal/client.py).
- **Found:** `_start_review` wraps the entire Temporal `sync_connect()` + `start_workflow` in `try/except Exception` and only logs (receivers.py:188-200) — it never re-raises. `_start_stamphog_review` is identically guarded ("the broker being down must never surface into the saver", try/except around `queue_inbox_pr_review`). So a Temporal _failure_ in the first callback cannot stop the second from running. The finding's severe outcome — Stamphog "never queued" — is unreachable.
- **Found:** The suggested "smallest change" (register Stamphog first, or one callback that queues Stamphog before ReviewHog) does NOT make the two dispatches "operationally independent." Django runs all `on_commit` callbacks serially in the same thread; ordering only decides which trigger waits behind the other's blocking network call. Reordering merely moves the risk to the other trigger — it does not decouple them, so the finding's core remedy misreads the mechanism.
- **Impact:** The only genuine residual is a _bounded delay_ (not loss) of the Stamphog Celery enqueue if the ReviewHog Temporal connect is slow during a Temporal outage. Both are best-effort, fire-and-forget advisory reviews dispatched post-commit on a background TaskRun-save path — the save has already committed, nothing user-facing or data-carrying is blocked, and during a Temporal outage ReviewHog's own review is failing regardless. The Stamphog leg is itself just a broker publish. This is a marginal, infra-outage-only reliability edge, and the only fix that would actually decouple them (a durable async outbox) is a heavyweight architectural addition — overengineering for this path. Fails the bar (severe claim is wrong, simple fix is a no-op, residual impact is low).

### [❌ dismissed] consider — products/review_hog/backend/api/settings.py:77-82

**Fail-soft Stamphog connection check can create noisy error logs**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `get_stamphog_connected` intentionally fails soft, but it logs every failure with `logger.exception` on a settings endpoint that the Code review page calls routinely. If the Stamphog product DB or its circuit breaker is unavailable, every page load can emit a full stack trace, creating log noise that makes the underlying outage harder to diagnose.
- **Suggestion:** Keep returning `False`, but throttle or cache the failure log for a short TTL per team, and include `team_id` in the log context. For expected circuit-open/read-unavailable cases, consider a warning with `exc_info=True` only when the throttle permits, reserving unthrottled `logger.exception` for unexpected errors.
- **Validator:** - **Checked:** `get_stamphog_connected` (products/review_hog/backend/api/settings.py:58-65 in the diff), when its `except` path fires, how the endpoint is invoked from the frontend (`reviewHogSettingsLogic.ts:446` `loadSettings` on mount), and the alpha-gating (`get_can_trigger_reviews` limits the UI to `settings.REVIEWHOG_TEAM_ID`).
- **Found:** The `logger.exception` only executes when `has_reviewable_repo_config(team_id)` raises — i.e. during an actual Stamphog product-DB / circuit-breaker outage. In steady state the except path never runs, so there is zero baseline noise. The settings read is fetched on scene mount (`await reviewHogSettingsRetrieve(currentProjectId())`), not a high-frequency poll, and the Code review page is alpha-gated to the designated ReviewHog team — so even during an outage the emission rate is bounded by occasional page loads, not request volume.
- **Impact:** This is a logging-hygiene / observability preference, not one of the keep categories (no correctness, security, data-loss, contract, or real-scale performance defect). It is the opposite of a "swallowed error that hides failures" — the error is logged loudly and the value fails soft to `False` as intended. The claim that stack traces "make the outage harder to diagnose" is weak: a handful of traces from a low-traffic settings endpoint during a dependency outage aids diagnosis rather than obscuring it, and Stamphog emits its own outage logs. The proposed remedy — per-team TTL-throttled failure logging plus expected-vs-unexpected tiering (`warning`/`exc_info`) — is observability infrastructure disproportionate to an informational UI flag, i.e. mild overengineering. Per precision-over-recall this does not clear the bar; the one trivially-valid sub-point (add `team_id` to the log) is too minor to surface on its own.

### [❌ dismissed] should_fix · security — tools/pr-approval-agent/review_pr.py:225-225,587-590

**Self-driving mode is not bound to bot-authored PRs before relaxing the draft gate**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The new self_driving flag is used directly to skip both the bot-author refusal and the draft prerequisite. That means any caller that passes self_driving=True for a human-authored draft PR will bypass the draft gate even though the carve-out is only intended for bot-authored self-driving implementation PRs. This is separate from parsing truthy values: even an exact boolean true on the wrong PR shape makes the engine review a human draft and gives the reviewer prompt machine-user provenance that does not apply.
- **Suggestion:** Fail closed by deriving an effective self-driving mode only after PR data is available, for example self.self_driving = self.self_driving and self.pr.author_is_bot before classification/gates run, and use that derived value for the draft relaxation, prompt classification, and output. In review_local.py, build PRData first, then apply the same author_is_bot check before the bot-author gate. If self_driving was requested for a non-bot author, either ignore the carve-out or return a refusal/escalation so malformed hosted context cannot weaken normal draft behavior.
- **Validator:** - **Checked:** Every call site that can set `self_driving` on the engine (`Pipeline`), and the server-side chain that derives the flag: `review_pr.py` Action entrypoint, `review_local.py`, `products/stamphog/backend/temporal/activities.py::run_review_in_sandbox`, and the two provenance-stamping legs in `tasks/webhooks.py` / `tasks.py`.
- **Found:** The Action runtime never sets the flag — `review_pr.py:966` calls `Pipeline(args.pr_number, args.repo, dry_run=..., verbose=...)` with no `self_driving` kwarg (defaults `False`). The only non-default setter is the hosted path: `activities.py` passes `self_driving_review=bool(output.get("inbox_review"))` into `build_reviewer_invocation`, which round-trips through the context JSON to `review_local.py`'s `Pipeline(..., self_driving=bool(context.get("self_driving_review")))`.
- **Found:** `inbox_review` provenance is stamped only for positively-identified bot authors. The webhook leg `_inbox_rereview_carve_out` returns an empty `_InboxCarveOut()` for any non-bot author via an explicit `if not _is_bot_authored(pr): return _InboxCarveOut()` guard (before any DB work), then further requires repo-native head, synced+enabled config, a team-scoped tasks-facade match, and the acting reviewer's toggle. The receiver leg `process_inbox_pr_review` is bot-authored by construction — its PR URL comes from a signals-implementation TaskRun whose PR is opened by the team's GitHub App machine user.
- **Impact:** `self_driving=True` cannot reach a human-authored draft through the actual call sites; producing it would require an upstream bug (the webhook `_is_bot_authored` gate failing, or a signals-implementation run carrying a human's PR URL). The proposed engine-level `author_is_bot` bind is therefore redundant with the parent caller's existing `_is_bot_authored` gate and guards a state the call sites already rule out — the criteria's "already handled by a parent caller" and "defensive-coding paranoia / speculative what-if" drop categories. The design intentionally centralizes positive identification at the server (the sandboxed engine has no DB access to re-verify task linkage), so a partial local check would not complete the validation it implies. Does not meet the bar.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1107-1183,1215-1223

**Receiver-leg reviews trust caller-supplied provenance before enabling the self-driving approval bypass**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `process_inbox_pr_review` is a new approval-capable entry point, but it treats `team_id`, `pr_url`, `signal_report_id`, and `task_run_id` as already-attested facts and immediately stamps `output={"inbox_review": ...}` on the `ReviewRun`. Downstream, `activities.py` turns any `inbox_review` provenance into `self_driving_review=True`, which relaxes the bot/draft gates and changes the trust context. Unlike the webhook leg, this path does not re-check that the supplied task run is the non-internal signal implementation run for this team, that its signal report id matches, that the PR URL belongs to the run/task repository, or that the fetched PR is the repo-native bot-authored self-driving shape. Since task-run output is a caller/agent-controlled contract elsewhere in the tasks product, a bad or compromised caller can point this path at another PR in an enabled repo and get it reviewed under the self-driving carve-out.
- **Suggestion:** Make `process_inbox_pr_review` fail closed unless it can independently re-attest the provenance before creating the `ReviewRun`. For example, after parsing/fetching the PR, call or extend the tasks facade to verify `team_id`, `task_run_id`, `signal_report_id`, repository, and `pr_url` all describe the same non-internal signal implementation run, and mirror the webhook carve-out's PR-shape checks (`head.repo.full_name` equals the base repo and author is a bot) before setting `inbox_review`. If any check fails, log and return without stamping self-driving provenance.
- **Validator:** - **Checked:** Traced the four provenance fields from review_hog's TaskRun receiver → `queue_inbox_pr_review` facade → `process_inbox_pr_review`, and compared against the webhook leg (`_inbox_rereview_carve_out`) and `find_signal_implementation_run`.
- **Found (partial correction to the finding):** Three of the four fields are actually server-attested, not caller-supplied — `team_id`/`signal_report_id`/`task_run_id`/`acting_user_id` come from the fired `TaskRun`/`Task` rows and the server-side reviewer resolver (`receivers.py` ~L108–216). The one genuinely caller-controlled field is `pr_url`: it is `output.get("pr_url")` (receivers.py:78), the tasks product itself annotates it `"originates from task-run output APIs, so it is caller-controlled"` (products/tasks/backend/facade/api.py:5342), and it is written through the `set_output` PATCH endpoint gated by `task:write` (products/tasks/backend/presentation/views/api.py:1110) — a scope the sandbox agent holds (`INTERNAL_SCOPES` includes `task:write`, posthog/temporal/oauth.py:37-38). So the self-driving agent, which runs an LLM over untrusted PR/signal content, can set `pr_url` to any value.
- **Found (the real gap):** `process_inbox_pr_review` (diff L1041-1166) parses the repo _from_ the agent-supplied `pr_url`, resolves any enabled `StamphogRepoConfig` for that repo, fetches whatever PR the URL names, and stamps `output={"inbox_review": ...}` with no re-attestation — it never calls `find_signal_implementation_run`, never checks bot-authorship/draft/fork-safety, and never verifies the `pr_url` belongs to `task_run_id`'s run. The webhook leg does all of this (diff L862-936) and its own comment calls it `"belt and braces for the boundary a compromised or refactored facade would otherwise silently widen."` The receiver even has `task.repository` in hand (receivers.py:88) but doesn't use it to constrain the URL.
- **Impact:** `activities.py` sets `self_driving_review=bool(output.get("inbox_review"))` (diff L1227), which relaxes the bot-author refusal, draft gate, per-repo `review_mode`, and author-write-permission gate, and the workflow posts a real head-pinned GitHub APPROVE. A prompt-injected/compromised self-driving agent can therefore point `pr_url` at an arbitrary PR in a team-enabled repo (same-repo, different PR number suffices — e.g. a dependabot PR or a LABEL-mode-excluded human PR) and obtain an unearned Stamphog approval that satisfies required reviews with zero human in the loop — exactly the hazard tasks.py:73-75 documents the bot-author refusal exists to prevent. This is a trigger-side bypass, which the PR's own design explicitly set out to avoid ("a positively identified carve-out rather than a trigger-side bypass"), so it also breaks a stated invariant. Meets the security / auth-gap keep bar with a concrete trigger and concrete consequence; the elevated precondition (needs a compromised agent + opted-in reviewer + enabled repo) is real but does not neutralize the exposure.

### [❌ dismissed] should_fix · code_quality — products/tasks/backend/facade/api.py:501-503

**Team scoping is applied after an unscoped task-run match**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_signal_implementation_run` calls the unscoped `find_task_run` first and only then checks `run.team_id != team_id`. If another team has a matching PR URL or repository/head branch and is selected first, this facade returns `None` even when the requested team has a valid matching implementation run. That makes the self-driving webhook carve-out fail nondeterministically for valid runs instead of enforcing team scope in the lookup itself.
- **Suggestion:** Apply the team filter before selecting a run. Either extend `find_task_run` to accept an optional `team_id` and include it in both the PR URL and branch querysets, or implement the equivalent team-scoped lookup directly in this facade so the selected candidate is drawn only from the requested team.
- **Validator:** - **Checked:** Read `find_task_run` (products/tasks/backend/webhooks.py:29-96) and the only caller of `find_signal_implementation_run`, the webhook carve-out `_inbox_rereview_carve_out` (diff L862-936), plus how `team_id` is derived there.
- **Found (premise is technically accurate but the trigger is unreachable):** `find_task_run` matches on `output__pr_url=pr_url` scoped to `task__repository__iexact=repository` (webhooks.py:41-42), else on `branch` + `repository` (webhooks.py:66-73) — neither leg is team-filtered, and `find_signal_implementation_run` applies `run.team_id != team_id` afterward (diff L1714). For a _valid requested-team run to be shadowed_, two different PostHog teams must both hold a run matching the **same** `pr_url` (+repo) or the **same** `branch` (+repo). A real GitHub PR URL is unique to the single run that opened it, so natural pr_url duplication across teams does not occur; the branch leg is only consulted when no run has recorded that pr_url, and self-driving head branches are task-specific `posthog-code/<slug>` names that don't collide across teams. The collision is a contrived multi-tenant coincidence, not something real inputs hit.
- **Found (isolation is not actually broken):** The post-match `run.team_id != team_id → None` check correctly _rejects_ a foreign-team run — there is no cross-tenant binding or data leak. In the plausible variant the reviewer's own scenario implies (config-team ≠ run-team, e.g. `_resolve_repo_config` picks the oldest config's team while another team actually opened the PR), returning `None` is the intended fail-closed outcome; the suggested team-scoped query would return `None` there too, so the fix changes nothing in that case.
- **Impact:** The only genuinely distinct consequence — a valid same-team run missed because a second team matched first — is fail-closed (a later-push re-review is skipped; the stale-approval dismissal path is unconditional and unaffected, and the initial draft review already ran via the receiver leg). Rare trigger + fail-closed + no isolation violation puts this under the skill's 'never-gonna-happen edge case / speculative what-if' drop bar rather than a correctness bug worth surfacing.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/reviewer.py:568-568,683-703

**Self-driving prompt still includes author familiarity when present**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving block is appended after `familiarity_block`, but nothing suppresses the existing author-familiarity trust signal when `cl["self_driving"]` is true. That contradicts the intended behavior described in the chunk: self-driving reviews should replace human-author trust context with verified task provenance. If the sandbox context ever contains `author_pr_numbers`, or if `Pipeline(..., self_driving=True)` is used outside the tokenless sandbox path, the prompt can contain both a positive author-familiarity block and a later warning that machine-user familiarity carries no signal. That gives the reviewer conflicting trusted context and can bias approval for bot-authored PRs based on the machine user's history.
- **Suggestion:** Make the suppression explicit in the engine, not only in the server context producer. For example, skip familiarity for self-driving runs before the prompt is built (`if self.self_driving: return` in `Pipeline._maybe_compute_familiarity` and `_attach_familiarity`), or have `_build_review_prompt` render `familiarity_block = ""` whenever `cl.get("self_driving")` is true. Also ensure `_render_review_body` does not add the author-familiarity bullet for self-driving runs.
- **Validator:** - **Checked:** Whether `familiarity` can be non-`None` while `self_driving` is `True` at prompt-build time — traced `_build_review_prompt`/`_format_familiarity`/`_format_self_driving` (reviewer.py), the familiarity populator `_attach_familiarity` (review_local.py), and the server producer `fetch_review_context` (activities.py), plus both engine entrypoints.
- **Found:** `_attach_familiarity` only sets `classification["familiarity"]` when `context.get("author_pr_numbers")` is truthy — review_local.py:302-304 `raw_prs = context.get("author_pr_numbers"); if not raw_prs: return`. With no numbers, familiarity stays `None` and `_format_familiarity(cl)` returns `""`.
- **Found:** The server sets `author_pr_numbers = []` for every inbox/self-driving review — `activities.py::fetch_review_context`: `is_inbox_review = bool((run.output or {}).get("inbox_review")); author_pr_numbers = client.get_author_merged_pr_numbers(...) if author and not is_inbox_review else []`. The PR's own integration test asserts `context["author_pr_numbers"] == []` for a self-driving run. So on the hosted path (the only path that sets `self_driving=True`) familiarity is `None` by construction and the two blocks never coexist.
- **Found:** The Action entrypoint never enables the flag (`review_pr.py:966` instantiates `Pipeline` without `self_driving`), so the finding's second hedge — `self_driving=True` outside the sandbox — does not occur in production.
- **Impact:** The conflicting-trust-signal prompt the finding describes is unreachable in the current code; producing it requires an upstream change (server populating `author_pr_numbers` on an inbox review, or a new non-sandbox caller enabling the flag). The suppression is already handled at the context producer, documented, and test-asserted, so the proposed engine-level suppression is defense-in-depth against a state the parent caller rules out — a speculative-what-if / already-handled drop, not a live bug. Does not meet the bar.

### [✅ VALID] must_fix · bug — products/tasks/backend/facade/api.py:503-506

**Implementation PR lookup filters out the Signals tasks it is meant to identify**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `find_signal_implementation_run` returns `None` when `task.internal` is true, but the Signals auto-start implementation path currently creates its implementation task with `internal=True` (`products/signals/backend/auto_start.py` passes `internal=True`, and tasks tests document that signal-report tasks are hidden by default this way). That means the webhook carve-out cannot positively identify the self-driving Inbox PRs this PR is trying to support, so later pushes will continue to be skipped as bot/draft PRs instead of being re-reviewed.
- **Suggestion:** Do not use `task.internal` as the discriminator here. Match the actual implementation-run shape used by Signals, for example `origin_product == SIGNAL_REPORT` plus the implementation run marker (`run.state["ai_stage"] == "implementation"`) or the existing Signals implementation association/artefact if that boundary is acceptable. Keep excluding unrelated internal plumbing tasks, but allow the internal implementation task that opens the PR.
- **Validator:** - **Checked:** The self-driving implementation task creation in `products/signals/backend/auto_start.py`, how `create_and_run_task` propagates `internal`, the discriminator in `find_signal_implementation_run` (diff L1717-1718), and the assumption encoded in review_hog's receiver + both test suites.
- **Found (premise confirmed):** `auto_start.py:258-261` creates the task that opens the draft PR — `interaction_origin="signal_report"` (comment: "Makes the agent auto-push and open a draft PR"), `ai_stage="implementation"` — with `internal=True` and a deliberate comment ("Internal so the run stays out of the default task list"). `create_and_run_task` forwards it unchanged (products/tasks/backend/facade/api.py:828 default, :850 `internal=internal`) into `Task.create_and_run` → `Task.internal`; no remap. `find_signal_implementation_run` then does `if task.signal_report_id is None or task.internal: return None` (diff L1718), so it rejects exactly the task shape it exists to identify.
- **Found (corroboration):** Every production signal-report task is `internal=True` — implementation (auto_start.py:261), research (report_generation/research.py:715), custom agents (custom_agent/base.py:683); the only `internal=False` is `management/commands/seed_inbox_data.py:279`, a dev seed. So `not task.internal` selects no real signal-report task. The PR's own test masks this: `_make_run` defaults `internal=False` (diff L1798), and review_hog's receiver test treats its `internal=True` case (`internal_pipeline_task`) as a skip — so green tests never exercise the real `internal=True` shape.
- **Impact:** The webhook carve-out (leg 2) gets `None` for every genuine self-driving PR, so `synchronize`/`reopen`/retarget pushes fall through to the bot/draft skip and are never re-reviewed — the carve-out is inert against production data. The same wrong assumption also sits on the pre-existing `if task.internal: return` in `receivers.py` that gates leg 1 (the initial review dispatch), so the feature is likely broadly non-functional, not just leg 2. Concrete trigger + concrete feature-breaking consequence, verified against the actual task-creation code; `must_fix` is warranted.
