# Reviewer-quality run — `G-gpt56luna-xhigh-1`

- **Dumped:** 2026-07-30T12:29:06+00:00
- **Report id:** `019fb2c4-b3da-7f27-be3b-116754d3d480` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 3865s (64.4 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-luna` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 13           | 16         | 14          | 3                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in       | cache write | cache read    | output      | >200K gens | true $     | gw $       |
| --------------- | --------------------------- | ------- | -------------- | ----------- | ------------- | ----------- | ---------- | ---------- | ---------- |
| claude-opus-4-8 | validation                  | 98      | 91,761         | 536,281     | 8,830,882     | 140,681     | 0          | $11.74     | $11.74     |
| gpt-5.6-luna    | review                      | 294     | 14,927,809     | 0           | 0             | 66,930      | 0          | —          | $3.77      |
| gpt-5.6-luna    | blind-spot                  | 48      | 2,515,503      | 0           | 0             | 14,111      | 0          | —          | $0.61      |
| claude-sonnet-5 | dedup                       | 1       | 7,050          | 0           | 0             | 4,994       | 0          | $0.06      | $0.06      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981          | 0           | 0             | 515         | 0          | $0.02      | $0.02      |
| **total**       |                             | **442** | **17,548,104** | **536,281** | **8,830,882** | **227,231** | **0**      | **$11.82** | **$16.20** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- `true $` total excludes unpriced model `gpt-5.6-luna` (342 gen(s), gw $4.37).
- naive method (all prompt tokens at input price): $50.89 — 4.3× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $12.1391 over 442 gen(s) (true $8.2521, Δ +47.1%)
  - · of which cache read: $5.9217 over 401 gen(s) (true $4.4154, Δ +34.1%)
  - · of which cache write: $3.3518 over 98 gen(s) (true $3.3518, Δ -0.0%)
  - · of which fresh (derived): $2.8656 over 442 gen(s) (true $0.4849, Δ +491.0%)
  - output: $4.0584 over 442 gen(s) (true $3.5721, Δ +13.6%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …8e18820a | issues-review-p2-c1 | 11:25:33  | 0             | 0              | gpt-5.6-luna    |
| …f2b0afc2 | issues-review-p3-c1 | 11:25:35  | 0             | 0              | gpt-5.6-luna    |
| …d0ec36a3 | issues-review-p3-c3 | 11:25:35  | 0             | 0              | gpt-5.6-luna    |
| …f15ae926 | issues-review-p1-c1 | 11:25:36  | 0             | 0              | gpt-5.6-luna    |
| …619f4ca9 | issues-review-p2-c2 | 11:25:37  | 0             | 0              | gpt-5.6-luna    |
| …e56eee38 | issues-review-p3-c2 | 11:25:37  | 0             | 0              | gpt-5.6-luna    |
| …a178c439 | issues-review-p2-c3 | 11:25:38  | 0             | 0              | gpt-5.6-luna    |
| …925ccf6b | issues-review-p1-c2 | 11:25:38  | 0             | 0              | gpt-5.6-luna    |
| …287d55ec | issues-review-p1-c3 | 11:25:38  | 0             | 0              | gpt-5.6-luna    |
| …b7f511d2 | issues-review-p3-c2 | 11:28:37  | 0             | 0              | gpt-5.6-luna    |
| …cb617c7c | issues-review-p1-c3 | 11:28:37  | 0             | 0              | gpt-5.6-luna    |
| …edb1e880 | issues-review-p1-c2 | 11:28:39  | 0             | 0              | gpt-5.6-luna    |
| …8db511ae | issues-review-p2-c1 | 11:28:39  | 0             | 0              | gpt-5.6-luna    |
| …f5d3e848 | issues-review-p3-c1 | 11:28:44  | 0             | 0              | gpt-5.6-luna    |
| …3e67a6ca | issues-review-p3-c3 | 11:28:47  | 0             | 0              | gpt-5.6-luna    |
| …35ed01a3 | issues-review-p2-c2 | 11:28:50  | 0             | 0              | gpt-5.6-luna    |
| …79465e07 | issues-review-p1-c1 | 11:28:56  | 0             | 0              | gpt-5.6-luna    |
| …13cf0169 | issues-review-p2-c3 | 11:28:56  | 0             | 0              | gpt-5.6-luna    |
| …a68e8a42 | issues-review-p2-c3 | 11:32:13  | 0             | 0              | gpt-5.6-luna    |
| …4461bc08 | issues-review-p3-c2 | 11:32:13  | 0             | 0              | gpt-5.6-luna    |
| …15f77917 | issues-review-p3-c3 | 11:32:14  | 0             | 0              | gpt-5.6-luna    |
| …e97de4f3 | issues-review-p2-c2 | 11:32:15  | 0             | 0              | gpt-5.6-luna    |
| …50c29f17 | issues-review-p3-c1 | 11:32:16  | 0             | 0              | gpt-5.6-luna    |
| …b1d3ef60 | issues-review-p1-c2 | 11:32:18  | 0             | 0              | gpt-5.6-luna    |
| …5aa40ed7 | issues-review-p1-c1 | 11:32:28  | 0             | 0              | gpt-5.6-luna    |
| …f55b8d73 | issues-review-p2-c3 | 11:34:56  | 0             | 0              | gpt-5.6-luna    |
| …374e3e4d | issues-review-p3-c1 | 11:35:00  | 0             | 0              | gpt-5.6-luna    |
| …231ee8f1 | issues-review-p1-c1 | 11:35:06  | 0             | 0              | gpt-5.6-luna    |
| …4a8fd08e | issues-review-p3-c2 | 11:35:12  | 0             | 0              | gpt-5.6-luna    |
| …5fe2cfee | issues-review-p2-c2 | 11:35:13  | 0             | 0              | gpt-5.6-luna    |
| …fed9506a | issues-review-p3-c3 | 11:35:27  | 0             | 0              | gpt-5.6-luna    |
| …7c98cba5 | issues-review-p2-c1 | 12:02:16  | 0             | 0              | gpt-5.6-luna    |
| …e34b7976 | blind-spots-c1      | 12:04:20  | 0             | 0              | gpt-5.6-luna    |
| …5c56f6ed | blind-spots-c2      | 12:04:23  | 0             | 0              | gpt-5.6-luna    |
| …dc221d7c | blind-spots-c3      | 12:04:24  | 0             | 0              | gpt-5.6-luna    |
| …fc42e214 | blind-spots-c4      | 12:04:28  | 0             | 0              | gpt-5.6-luna    |
| …294929fc | validation-c2       | 12:08:01  | 0             | 37,687         | claude-opus-4-8 |
| …df37a609 | validation-c3       | 12:08:03  | 0             | 36,819         | claude-opus-4-8 |
| …47fabd34 | validation-c4       | 12:08:04  | 17,141        | 19,622         | claude-opus-4-8 |
| …278954cb | validation-c1       | 12:08:06  | 17,141        | 20,147         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **2/40** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 11s      |
| review wave (perspectives)  | 39m 03s  |
| blind-spot sweep            | 2m 36s   |
| dedup (incl. combine/clean) | 49s      |
| validation                  | 21m 01s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 41m 39s — the reviewer-model speed comparison number.
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
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 2          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | review-hog-blind-spots-general                 | 1          |
| 1000 | 2     | review-hog-blind-spots-general                 | 2          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | review-hog-blind-spots-general                 | 1          |

## Findings (post-dedup) with validator verdict

### [✅ VALID] should_fix (validator→consider) · bug — products/review_hog/backend/receivers.py:144-158

**Honor opt-in from any assigned reviewer**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The resolver selects only one canonical assigned reviewer and then gates Stamphog on that user's toggle. This does not implement the stated contract that Stamphog should run when at least one assigned reviewer has opted in: if the first reviewer is opted out but another assigned reviewer is opted in, the PR is skipped entirely.
- **Suggestion:** Resolve the full assigned reviewer set for the Stamphog path, select an opted-in reviewer when any exists, and use that reviewer as the acting identity for the queued review. Keep the existing single-reviewer resolution for ReviewHog if that behavior is intentional.
- **Validator:** - **Checked:** the actual PR diff for `receivers.py` (working tree is at master, not the PR head, so I pulled `gh pr diff 75215`), tracing both the initial-trigger leg (`handle_task_run_saved`) and the webhook re-review leg (`resolve_stamphog_acting_reviewer`), plus `_resolve_assigned_reviewer` and the `queue_inbox_pr_review` call.
- **Found:** `_resolve_assigned_reviewer` returns exactly one identity — `acting = next((user for user in resolved if user.id == task_created_by_id), resolved[0])` (receivers.py, the `acting = next(...)` line). Both stamphog gates then read `stamphog_review_inbox_prs` off that single `acting_user_id` (the `if pr_url is not None and settings.stamphog_review_inbox_prs:` block, and `resolve_stamphog_acting_reviewer`). So a report with ≥2 resolved reviewers where the canonical one (task creator, else first resolved) is opted out but another opted in → stamphog is skipped. This does contradict the PR's repeated 'at least one of the assigned users' / 'any assigned reviewer' / 'nobody is opted in' contract.
- **Found (counter-evidence):** the same PR adds a docstring documenting the design as deliberate — 'The same resolved acting reviewer carries a second, independent toggle' — and the ReviewHog leg gates on the identical single acting reviewer (the finding itself accepts that as intentional). So the discrepancy is really an internal contradiction between the PR prose and the code's own documented single-acting-reviewer model, resolvable by fixing either side.
- **Impact:** a genuine, reachable behavioral gap (an opted-in non-canonical reviewer's preference is silently ignored), but narrow — it needs a multi-reviewer report with mismatched toggles, on a draft experiment branch, and the consequence is a missed review, not wrong output/data loss/security. Worth surfacing so the author reconciles code vs. description, but the documented single-reviewer design and narrow blast radius put it below should_fix.
- **Priority:** lowered to `consider` — real discrepancy on record, but plausibly a documentation mismatch rather than a code defect, and low-impact at this stage.

### [❌ dismissed] should_fix · security — products/stamphog/backend/tasks/tasks.py:113-121

**Strictly validate inbox PR URLs**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `_parse_pr_url` uses an unanchored regex that searches for `github.com/` anywhere in the input and accepts arbitrary characters in the owner/repository segment. For example, a URL hosted on a lookalike domain can be interpreted as a GitHub PR URL, and malformed paths can be accepted. Since this value originates from a task output and controls which configured repository and PR number are fetched, the parser should enforce the actual host and exact path shape.
- **Suggestion:** Parse with `urllib.parse.urlparse`, require an allowed scheme and `netloc == "github.com"` (or the configured GitHub host), and validate the path against an anchored pattern such as `^/[^/]+/[^/]+/pull/[1-9][0-9]*/?$`. Reject query/fragment variants unless explicitly supported.
- **Validator:** - **Checked:** the only caller of `_parse_pr_url`, `process_inbox_pr_review` in `products/stamphog/backend/tasks/tasks.py`, and how the parsed `(repository, pr_number)` flow into the config lookup and the GitHub fetch; also the caller chain (`queue_inbox_pr_review` facade ← review_hog receiver) that supplies `pr_url` and `team_id`.
- **Found:** the parsed `repository` is used solely as a lookup key: `StamphogRepoConfig.objects.for_team(team_id).filter(provider="github", repository__iexact=repository, enabled=True, connected_by_user_id__isnull=False).exclude(installation_id="")`. A lookalike-host or malformed URL that yields a non-configured owner/repo simply misses and returns (`stamphog_inbox_pr_repo_not_reviewable`).
- **Found:** the URL is never fetched. The actual GitHub call is `StamphogGitHubClient(repo_config.installation_id).get_pr(repo_config.repository, pr_number)` — it uses the config's **canonical** repo and the team's own installation, so only `pr_number` (always `\d+`, `int()` can't crash) comes from the parsed string. Host enforcement therefore prevents no SSRF/redirect.
- **Found:** `team_id` is an explicit task argument scoping every read/write (`for_team(team_id)`), not derived from the URL — no cross-tenant/IDOR surface.
- **Impact:** the claimed consequences (lookalike domain, malformed path) are neutralized downstream by the team-scoped enabled-config lookup and canonical-repo fetch; no concrete reachable failure can be named. The only residual concern — an arbitrary `pr_number` within an already-enabled repo — is not closed by the proposed host/path anchoring (a well-formed `github.com/<configured-repo>/pull/<N>` still parses) and is bounded to repos the team already enabled with the reviewer opted in. This is defensive hardening the surrounding validation already covers, so it does not meet the bar.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Validate the self-driving flag strictly as a boolean**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This flag relaxes the bot-author and draft gates, but `bool(context.get("self_driving_review"))` treats any non-empty string as true, including values such as `"false"` or `"0"`. A malformed or incorrectly serialized hosted context could therefore authorize the privileged self-driving carve-out and allow a bot-authored draft PR through.
- **Suggestion:** Require the exact JSON boolean value, for example `self_driving=context.get("self_driving_review") is True`, and ideally reject or log malformed non-boolean values when constructing the hosted context.
- **Validator:** - **Checked:** the full producer→consumer path for `self_driving_review`: `run_review_in_sandbox` (activities.py) → `build_reviewer_invocation` (logic/reviewer.py) → JSON context file → `review_local.run` at review_local.py:321.
- **Found:** the value is stamped by `build_reviewer_invocation(self_driving_review=bool(output.get("inbox_review")))`, whose parameter is typed `bool`, and written as `context = {..., "self_driving_review": self_driving_review}` then `json.dumps`-ed. The engine reads it back with `json.load`, so `context.get("self_driving_review")` is always a genuine Python `bool` (or `None` for the Action-shaped context that omits the key). There is no code path that serializes this key as a string.
- **Found:** the context is server-generated from task provenance (`ReviewRun.output["inbox_review"]`), not from PR body / untrusted author text — so it is not attacker-controllable, and the carve-out direction is fail-closed: absent/`False`/`None` all yield `bool(...) == False`.
- **Impact:** the flagged `bool("false")`-style hazard requires a truthy non-boolean string to reach the key, which the typed `bool` construction and `json.dumps` round-trip rule out. `bool(...)` and the suggested `is True` produce identical results for every value this pipeline can actually emit. This is defensive-coding paranoia against an unreachable input — per the criteria (speculative what-if / condition that can't occur given the call sites and types), drop it.

### [❌ dismissed] should_fix · bug — tools/pr-approval-agent/review_pr.py:937-938

**Skip author-familiarity signals for self-driving reviews**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The new self_driving flag is recorded and passed to the prompt, but `_maybe_compute_familiarity` still computes and exposes the bot author's familiarity for T1 reviews. The reviewer prompt renders that signal before the self-driving provenance block, and `_render_review_body` can also publish author-familiarity bullets. This contradicts the stated behavior that machine-author familiarity and merged-PR history carry no signal, and a bot with prior activity could receive inappropriate trust weight.
- **Suggestion:** When self_driving is enabled, skip `_maybe_compute_familiarity` or leave classification["familiarity"] unset, and suppress any author-familiarity review-body bullet for that path. Add a focused regression test asserting that a self-driving review contains no familiarity signal.
- **Validator:** - **Checked:** which code path a self-driving run actually executes, and where familiarity is computed vs. suppressed — `review_pr.py::run`/`_maybe_compute_familiarity` (the Action path) versus `review_local.py::run`/`_attach_familiarity` (the hosted path), plus the server-side context builder in `activities.py::fetch_review_context`.
- **Found:** `self_driving` is only ever set by `review_local.py::run` (`Pipeline(..., self_driving=bool(context.get("self_driving_review")))`); that entrypoint drives the pipeline manually (`_classify` → `_run_gates_offline` → `_attach_familiarity` at review_local.py:348 → `_llm_review`) and never calls `_maybe_compute_familiarity`. `review_pr.py::run` (which does call `_maybe_compute_familiarity` at review_pr.py:241) is the Action entrypoint, and nothing in the Action runtime sets `self_driving`, so it always runs with `self_driving=False` and a bot author still hits `_refuse_bot_author` before familiarity.
- **Found:** `_attach_familiarity` early-returns when `author_pr_numbers` is empty (review_local.py:301-304, `if not raw_prs: return`), leaving `classification["familiarity"]` = None (set by `_classify`, review_pr.py:464) and `self.familiarity` = None. The server empties `author_pr_numbers` for every inbox/self-driving review: `activities.py::fetch_review_context` computes `is_inbox_review` and sets `author_pr_numbers = ... if author and not is_inbox_review else []`. Both `author_pr_numbers` emptying and the `self_driving_review` flag are keyed off the same `run.output["inbox_review"]` provenance, so they are coupled — a self-driving run always has empty PR numbers.
- **Found:** with `classification["familiarity"]` = None, `_format_familiarity` renders no signal into the prompt and `_render_review_body` (review_pr.py:855, `fam = self.classification.get("familiarity")`) emits no author-familiarity bullet. The requested regression coverage already exists: `test_integration.py::test_inbox_review_approves_a_selfdriving_draft_pr_end_to_end` asserts `context["author_pr_numbers"] == []` ("the machine user's merged-PR history must not feed familiarity").
- **Impact:** the finding's premise — that a self-driving review computes and exposes the bot author's familiarity — does not hold; the stated no-machine-familiarity behavior is enforced (server-emptied `author_pr_numbers` + `_attach_familiarity` early-return), just via a different mechanism than the `review_pr.py` path the finding inspected. Wrong/unreproducible, so it does not meet the bar.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:210-236

**preserve failed initial stamphog queues for retry**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** If the Celery broker is unavailable, `queue_inbox_pr_review` raises and this handler only logs the exception. Because the initial Stamphog review is not backed by a GitHub webhook delivery, the review is permanently lost unless another TaskRun save or PR push happens. The callback also performs broker I/O synchronously in the TaskRun save path.
- **Suggestion:** Use a durable outbox or a retryable enqueue operation for the initial review, with bounded producer timeouts. Persist the pending handoff before commit and retry it asynchronously so broker failures neither block TaskRun saves nor silently discard the review.
- **Validator:** - **Checked:** `_start_stamphog_review` (receivers.py L210–236 in the PR head) and its call site, plus the sibling `_start_review` (Temporal leg) it was modeled on, and the PR's own Case 2 recovery path.
- **Found (deliberate, documented posture):** the catch-log fire-and-forget is intentional and explicitly documented — the docstring reads 'Fire-and-forget the hosted Stamphog review; the broker being down must never surface into the saver.' It is a verbatim copy of the established `_start_review`/Temporal leg in the same file, which likewise wraps a downstream dispatch in `try/except Exception: logger.exception(...)`. Neither leg was designed to be durable; the file's whole philosophy is that a TaskRun save must never break because downstream infra (Temporal, the Celery broker) is momentarily down.
- **Found (recovery exists):** the 'permanently lost' framing is overstated — the review is only dropped if the broker is down at that exact on_commit moment AND no further push ever lands. Per the PR's Case 2, later commits on a self-driving PR re-review through stamphog's webhook path (`resolve_stamphog_acting_reviewer`), so for the iterating draft PRs this feature targets, a transient broker blip on the initial queue is recovered on the next push.
- **Found (sync-I/O claim):** the callback runs via `transaction.on_commit` (after the transaction closes, not holding it open) and the docstring notes the facade only does a broker publish ('the only work on this save path is the broker publish') — a single Celery enqueue, identical in cost profile to the sibling Temporal-start already accepted on this path.
- **Impact:** the suggested fix (durable outbox, retryable enqueue, bounded producer timeouts, persist-before-commit) is a substantial reliability-infra pattern that contradicts the deliberately-chosen, documented, sibling-consistent design — textbook overengineering for an experiment-stage feature (draft PR on a frozen experiment branch). The failure mode is rare and the consequence mild and recoverable, so it does not meet the bar.

### [❌ dismissed] must_fix · best_practice — products/stamphog/backend/tasks/tasks.py:1107-1110

**Persist or reconcile failed initial review dispatches**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The receiver queues this task as fire-and-forget, while the task gives up after only three retries. If the broker, database, or GitHub remains unavailable through those attempts, the initial inbox review is silently lost because no durable pending-review record or reconciliation path is created. A later TaskRun save is not guaranteed, so the PR can remain unreviewed indefinitely.
- **Suggestion:** Persist the requested review (for example, on the TaskRun or in a dedicated outbox row) before dispatching, and add a reconciler that resumes pending reviews. At minimum, use a longer/backoff retry policy with an observable terminal failure and a durable retry path rather than relying on another output save.
- **Validator:** - **Checked:** `process_inbox_pr_review` in `products/stamphog/backend/tasks/tasks.py` (decorator, all three retry paths), its receiver dispatch in `products/review_hog/backend/receivers.py` (`_start_stamphog_review` → `queue_inbox_pr_review` under `transaction.on_commit`), and the webhook re-review carve-out `_inbox_rereview_carve_out` that runs on later deliveries.
- **Found:** every failure branch (`stamphog_inbox_pr_config_resolution_failed`, `stamphog_inbox_pr_fetch_failed`/`_rate_limited`, `stamphog_inbox_pr_create_run_failed`) logs via `logger.exception`/`warning` and then `raise ...retry(exc=e)`; retry exhaustion raises Celery's `MaxRetriesExceededError`. The outcome is a logged terminal failure, not the code-level 'silent' loss the finding describes.
- **Found:** the task docstring states the initial leg is a convenience to have the verdict ready at draft-triage time, and that later head-changing events re-review through the webhook carve-out; the receiver re-fires on every TaskRun output save (runs typically save output more than once), and a refire after an undelivered head still reviews. So the durable/authoritative review path is the webhook leg, by design — the initial leg is deliberately best-effort.
- **Impact:** a permanently-failed initial dispatch loses only an _optional_ pre-review of a toggle-gated experimental feature; it posts no approval, so the stale-approval safety invariant is untouched, and any subsequent push or output re-save recovers it. The only genuinely stuck case is a draft that never receives another commit or save — a rare, low-impact tail whose consequence is a missing nice-to-have, not data loss or a safety hole. This does not meet the reliability bar.
- **Impact:** the proposed remedy (a persisted outbox row plus a reconciler resuming pending reviews) is disproportionate durability machinery for a best-effort leg — overengineering under the validation criteria — and the must_fix severity is unsupportable for a safe, recoverable, logged failure.

### [❌ dismissed] should_fix · code_quality — products/stamphog/backend/facade/api.py:122-126

**Filter the reviewable-config check to supported providers**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** `has_reviewable_repo_config` checks enabled and synced configs but does not restrict the provider to GitHub, while both the initial task and webhook path explicitly resolve only `provider="github"`. Any synced non-GitHub config would therefore enable the inbox toggle even though the queued review can never be processed for that repository.
- **Suggestion:** Add `provider="github"` to the queryset, matching the provider filters used by the actual review paths.
- **Validator:** - **Checked:** `has_reviewable_repo_config`'s queryset in `products/stamphog/backend/facade/api.py` against how `provider`, `installation_id`, and `connected_by_user_id` are actually set — the model (`models.py:26-29`), the create serializer (`presentation/serializers.py:74-104`), both sync-create sites, and the manual-config adoption helper.
- **Found:** the helper requires BOTH `connected_by_user_id__isnull=False` AND non-blank `installation_id` (`.exclude(installation_id="")`). Both are set together only by the authenticated GitHub sync flow, which hardcodes `provider="github"` (`tasks/tasks.py:551` create; `presentation/views.py:307` `get_or_create(provider="github", ...)`).
- **Found:** the only path that lets a client set a non-github `provider` is the plain serializer create, but there `installation_id` is `read_only` ('Set only by the verified sync_installation flow; ignored on direct writes', `serializers.py:98-99`) and `connected_by_user_id` is not a serializer field (`fields` list, `serializers.py:74-85`). And `_adopt_preexisting_config` filters `provider="github"` (`views.py:66+`), so a manual non-github row is never adopted into a synced one.
- **Impact:** a config with `provider != "github"` can never simultaneously carry a non-blank installation_id and a connecting user, so it can never pass this check — the flagged scenario is unreachable. Even if it were, the helper only drives the UI toggle's enabled/disabled state; the actual review path filters `provider="github"` and no-ops, so the worst case is a cosmetic toggle mismatch, not a processing bug. Adding the filter is harmless consistency but guards a state that can't occur with the only implemented provider — speculative future-proofing, below the bar.

### [❌ dismissed] should_fix · documentation — products/stamphog/AGENTS.md:88-95

**Documented carve-out does not match the current implementation**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** This section documents an implemented self-driving exception using `self_driving_review`, `Pipeline(self_driving=...)`, `ReviewRun.output["inbox_review"]`, and `queue_inbox_pr_review`, but those contracts are not present in the checked-out code. The actual inbox receiver starts `start_review_pr_workflow` directly with `trigger_source="inbox"`, while `review_local.py` still unconditionally refuses bot authors and the Stamphog webhook pre-filter still rejects drafts and bot-authored PRs. This makes the security and behavior documentation materially misleading and could cause future changes to rely on nonexistent gates.
- **Suggestion:** Either update the documentation to describe the actual `trigger_source`/`signal_report_id` flow and current bot refusal behavior, including the README entry point, or land the corresponding implementation before documenting this exception. Verify every referenced symbol and gate with a regression test before retaining the carve-out contract.
- **Validator:** - **Checked:** Pulled the real PR #75215 diff (`gh pr diff`) and grepped every symbol the finding names, then read the implementing hunks in `facade/api.py`, `facade/inbox_hooks.py`, `logic/reviewer.py`, `tasks/tasks.py`, `temporal/activities.py`, and `tools/pr-approval-agent/reviewer.py`.
- **Found:** Every documented contract is implemented _in this PR_, not absent: `queue_inbox_pr_review` is a new facade fn in `products/stamphog/backend/facade/api.py`; `process_inbox_pr_review` is the receiver leg in `tasks/tasks.py`; `facade/inbox_hooks.py` is a new resolver module; the engine flag flows `ReviewRun.output["inbox_review"]` → `self_driving_review=bool(output.get("inbox_review"))` (`temporal/activities.py`) → `Pipeline(self_driving=...)` (`tools/pr-approval-agent/reviewer.py`, `review_local.py`).
- **Found:** The reviewer's claimed alternative mechanism does not exist — `trigger_source` has **0** occurrences across the 2222-line diff. The bot/draft gates are _not_ unconditional: `tasks/tasks.py` adds `_inbox_rereview_carve_out` and bypasses the pre-filter with `if skip_reason is not None and inbox_review is None:`, and the engine relaxes the refusal via `reviewer.py::_format_self_driving` keyed on `cl.get("self_driving")`.
- **Found:** The on-disk checkout is the base, not the PR head — `HEAD` is `fe6ca668` (an unrelated data-imports commit), the PR head `1341596e` is not even fetched locally, and `products/stamphog/AGENTS.md` on disk is 113 lines with no carve-out section. This is exactly the tree the finding describes as 'the checked-out code.'
- **Impact:** The premise (documentation describes contracts the code doesn't implement) is mistaken — doc and implementation are consistent _within the PR_. The finding is an artifact of validating the PR's docs against a base tree lacking the PR's code, so it meets the 'Wrong / unreproducible' drop bar and would be a false positive to the author.

### [✅ VALID] must_fix (validator→should_fix) · security — products/stamphog/backend/tasks/tasks.py:1152-1162

**Revalidate the fetched PR before enabling the self-driving carve-out**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial inbox path fetches the PR and then unconditionally stamps `inbox_review`, which causes the engine to bypass bot-author, draft, fork, author-association, and write-permission safeguards. Unlike `_inbox_rereview_carve_out`, it never verifies that the fetched PR is bot-authored, repository-native, or otherwise matches the positively identified self-driving task. A malformed or manipulated `pr_url`/TaskRun output could therefore make Stamphog approve an arbitrary PR in a configured repository, including a fork or human-authored PR.
- **Suggestion:** After fetching the PR, apply the same identity checks as the webhook carve-out: require a bot author, a draft if that is part of the self-driving contract, and `head.repo.full_name` to match the configured repository. Also resolve `task_run_id` in the supplied team and verify its signal report, repository, and PR URL/branch match the fetched PR before creating the run; otherwise return without setting `inbox_review`.
- **Validator:** - **Checked:** `process_inbox_pr_review` (initial leg) vs `_inbox_rereview_carve_out` (webhook leg) in `products/stamphog/backend/tasks/tasks.py`; the engine's `self_driving` handling in `tools/pr-approval-agent/review_pr.py`/`review_local.py`; and how `output.pr_url` is written in `products/tasks/backend/` (agent-server observation + webhook backstop `_record_run_pr_url`).
- **Found (asymmetry):** the webhook leg positively identifies a self-driving PR with three checks before granting provenance — `_is_bot_authored(pr)`, fork-safety `head_repo.lower() != repo.lower()`, and a team-scoped `find_signal_implementation_run` task match. The initial leg does NONE of these on the fetched PR: after `get_pr(repo_config.repository, pr_number)` it unconditionally stamps `output={"inbox_review": {...}}` on the run.
- **Found (bypass is real):** in the engine, `self_driving` relaxes exactly the bot-author refusal (`if self.pr.author_is_bot and not self.self_driving`) and the draft prerequisite (`if pr.draft and not self.self_driving`), with no independent fork/association re-check — the engine explicitly delegates 'positively linked' verification to the hosted runtime. So the run's `inbox_review` stamp alone lets the engine post a real GitHub APPROVE on a bot/draft/fork PR.
- **Found (why the webhook leg's checks matter):** both legs ultimately trust `output.pr_url`, but the webhook leg re-validates the actual PR object on top (bot-author + non-fork). The initial leg trusts `output.pr_url` — written by an LLM agent's observed PR creation (untrusted-content threat model per the product's own invariants) or a branch-matched backstop — without re-validating the fetched PR at all.
- **Impact:** if `output.pr_url` ever resolves to a non-self-driving PR (fork or human-authored) in a configured+enabled repo, stamphog would review and could auto-approve it, satisfying required reviews with no human — the exact catastrophe the bot/fork/association gates exist to prevent (tasks.py bot-author comment; product CLAUDE.md stale-approval/trust-boundary invariants). The fix reuses existing helpers (`_is_bot_authored`, the fork check), so parity with the webhook leg is cheap.
- **Priority:** lowering must_fix → should_fix. The gap and its severe consequence are verified, but the direct exploit requires `output.pr_url` to point at a non-bot/fork PR, and the normal write paths are server-mediated (bot-observed creation; backstop match on a randomly generated `wizard_head_branch`), so adversarial control of that value is a narrow, unconfirmed vector; the feature is also per-user-toggle-gated and requires a synced+enabled config. This is a safety-critical consistency gap to bring to parity before broad rollout, not a confirmed merge-blocking exploit.

### [✅ VALID] must_fix (validator→consider) · bug — products/review_hog/backend/receivers.py:114-138

**check all assigned reviewers for Stamphog opt-in**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The Stamphog dispatch is gated only by the canonical acting reviewer returned by `_resolve_assigned_reviewer`. If that reviewer has `stamphog_review_inbox_prs` disabled but another assigned reviewer has it enabled, the Inbox PR is never queued, contrary to the feature requirement that any assigned reviewer opting in should enable the Stamphog review.
- **Suggestion:** Resolve the assigned reviewers separately for the Stamphog path and select an opted-in reviewer, or return the full resolved assignment set and dispatch when `any(user_settings.stamphog_review_inbox_prs for user in assigned_reviewers)` is true. Apply the same selection rule in `resolve_stamphog_acting_reviewer` so later webhook re-reviews remain consistent.
- **Validator:** - **Checked:** `_resolve_assigned_reviewer` and both its consumers (the initial dispatch in `handle_task_run_saved` and the webhook-leg `resolve_stamphog_acting_reviewer`) in the PR diff, plus the added tests in `test_inbox_trigger.py`.
- **Found (premise is factually correct):** `_resolve_assigned_reviewer` returns a single identity — `acting = next((user for user in resolved if user.id == task_created_by_id), resolved[0])` — and the stamphog gate reads `stamphog_review_inbox_prs` off that one user in both the initial-queue and webhook paths. So a report with ≥2 resolved reviewers where the canonical one is opted out but another opted in does skip the stamphog review, contrary to the PR prose's 'any assigned reviewer'.
- **Found (deliberate, tested design cuts against must_fix):** this is a duplicate of the contracts-perspective finding on the same code. The single-acting-reviewer model is documented in the code's own added docstring ('The same resolved acting reviewer carries a second, independent toggle'), mirrors the identical ReviewHog gating, and every added test exercises exactly one reviewer (`_suggest_reviewers(["alice"])` at diff L347/370/383/401). Implementation, docstring, and tests all consistently encode single-reviewer gating — the 'any assigned reviewer' contract lives only in imprecise PR prose, so the mismatch is as likely a description bug as a code bug.
- **Impact:** a real but narrow, reachable gap (an opted-in non-canonical reviewer's preference is ignored) on an experiment-stage draft PR, recoverable on a later push per the webhook re-review path. Not a clear correctness defect that must block merge.
- **Priority:** lowered from `must_fix` to `consider` — the same reasoning as the contracts-perspective duplicate: a genuine intent-vs-implementation discrepancy worth the author reconciling (fix the code or the wording), but plausibly deliberate, narrow in blast radius, and not a must-fix bug.

### [❌ dismissed] should_fix · bug — products/tasks/backend/facade/api.py:501-514

**should_fix: avoid cross-team task-run matches shadowing the valid run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `find_signal_implementation_run` calls the global `find_task_run` and only checks `run.team_id` after the lookup. If the same GitHub repository is connected to multiple teams, a newer matching run from another team can be selected by the URL or branch lookup, fail the team check, and cause the function to return `None` without considering the valid run belonging to the requested team. This makes inbox reviews nondeterministically disappear in multi-tenant setups.
- **Suggestion:** Apply the team constraint inside the lookup, either by adding a `team_id` parameter to `find_task_run` and filtering both URL and branch legs before ordering, or by querying candidate runs in this facade and continuing past non-matching-team/non-signal runs until the requested team's signal implementation run is found.
- **Validator:** - **Checked:** `find_signal_implementation_run` (facade, diff ~line 1694) and the `find_task_run` it delegates to (`products/tasks/backend/webhooks.py:30-99`), plus the single caller `_inbox_rereview_carve_out`, which always passes both `pr_url=pr.html_url` and `head_branch`.
- **Found:** `find_task_run`'s pr_url leg (`webhooks.py:42-60`) filters `output__pr_url=pr_url` + `task__repository__iexact=repository`. A GitHub PR html_url is globally unique and is recorded on exactly one run (the one that opened/bound it), so no second run in another team shares that `output.pr_url`. The 'newer cross-team run shadows the valid same-team run' mechanism the finding describes has no valid same-team run to shadow — there is at most one run per pr_url binding.
- **Found:** the `run.team_id != team_id` check is a deliberate fail-closed tenant guard (docstring: 'no caller can accidentally bind a PR to another tenant's run'), not a run selector. If the unique run for this PR belongs to another team, returning None is the intended safe outcome.
- **Found:** cross-team candidate collision is possible only in the branch fallback (`webhooks.py:69-79`, unordered `.first()`), which is reached solely when the pr_url leg misses — requiring the same repo connected to multiple teams AND a colliding non-wizard branch AND an unrecorded pr_url simultaneously.
- **Impact:** the primary (pr_url) path — the one always exercised here — cannot exhibit the described shadowing; the branch-fallback variant is a compound, vanishingly rare multi-tenant edge whose worst case is one missed re-review of an experimental toggle-gated feature, recoverable on the next push. This is a speculative never-gonna-happen edge, below the bar.

### [❌ dismissed] should_fix · performance — products/review_hog/backend/receivers.py:111-138

**avoid repeated full resolver work on hot TaskRun saves**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Every qualifying `TaskRun` output save resolves the latest reviewer artefact and organization membership, loads settings, and can enqueue another Stamphog task. TaskRun is a hot model and the receiver intentionally re-fires on unchanged targets, so repeated saves can cause substantial database and broker work even when the PR head has not changed. The downstream task deduplicates only after it fetches GitHub state.
- **Suggestion:** Add a cheap persisted/idempotency watermark for the Stamphog handoff, such as the last queued PR URL/head or a unique pending-handoff record, and skip enqueueing when the target has not changed. Keep the webhook path responsible for new-head re-reviews.
- **Validator:** - **Checked:** the receiver's cheapest-first guard ordering (`handle_task_run_saved`), whether the flagged resolver work is net-new, and the downstream `process_inbox_pr_review` Celery task's dedup path in the PR diff.
- **Found (resolver work is shared, not net-new, and already an accepted re-fire cost):** the `_resolve_assigned_reviewer` + `ReviewUserSettings.load` calls the finding points at (L111–138) are the same resolver the pre-PR ReviewHog leg already ran on every qualifying re-fire — the stamphog leg only adds a boolean `settings.stamphog_review_inbox_prs` check on the already-loaded settings plus one `on_commit` enqueue. The receiver docstring already documents and accepts these re-fires ('Repeat saves with an unchanged target re-fire it deliberately'), and the resolver is gated behind narrow cheapest-first guards (not created, output touched, not FAILED/CANCELLED, has target, signal_report_id set, non-internal) — so it runs only for the one non-internal signal-report implementation task, a tiny slice of TaskRun saves, not the 'hot model' at large.
- **Found (the redundant downstream fetch is inherent, and the re-fire is a deliberate backstop):** the downstream task's own comments state the dedupe 'keys on the PR's current head, which only GitHub knows', so the GitHub fetch must precede dedup — the receiver holds only the PR URL and branch name, never the head SHA. The re-fire-then-fetch is an intentional reliability backstop: 'a refire after a head the webhook leg never delivered — a lost synchronize — still reviews the new commits.'
- **Impact / why it fails the bar:** the suggested receiver-side watermark ('last queued PR URL/head') is unworkable as stated — keying on PR URL would suppress the deliberately-preserved lost-synchronize recovery, and keying on head requires the very GitHub fetch it aims to avoid. The actual cost is bounded (one enqueue + one async GitHub fetch per agent-turn output save, experiment-scoped to opted-in users), runs off the save path in Celery, and correctly no-ops downstream on an unchanged head. This is a deliberate, documented design tradeoff, not an N+1 / unbounded / quadratic hot-path defect — it doesn't meet the performance bar.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:114-138

**Keep the two post-commit dispatches independent**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** These callbacks run in registration order with Django's default `robust=False`. If the ReviewHog callback raises before its internal try block, such as during a deferred import, Django stops executing later commit callbacks and the Stamphog review is never dispatched, even though its toggle is enabled.
- **Suggestion:** Register the callbacks with `robust=True`, or ensure each callback catches all exceptions including deferred imports, so a failure in one product's dispatch cannot suppress the other product's independent review.
- **Validator:** - **Checked:** the two `on_commit` registrations in `handle_task_run_saved` (review leg registered first, stamphog second), the full body of `_start_review` (L164–201, unchanged by this PR), and what can raise before its internal `try`.
- **Found (premise is technically real but has a single, narrow trigger):** the only statements outside `_start_review`'s `try` are its two deferred imports (`from ...temporal.client import start_review_pr_workflow`, `...temporal.types import TRIGGER_INBOX`) plus dict construction from already-bound locals that cannot raise. The Temporal RPC itself is inside the `try`. So the _only_ propagating failure is the deferred import of review_hog's own temporal package. That module is cached in `sys.modules` after the first successful import and can only fail under a systemic deploy/environment breakage (missing temporalio/PyGithub, an activity-registration error in the package `__init__`) — not a transient or per-PR condition.
- **Found (impact coincides with an already-dead feature):** if that import fails, `_start_review` fails for _every_ inbox review in the process — ReviewHog's inbox path is entirely non-functional in that deploy. The finding's added consequence is only 'and the stamphog leg is also suppressed', and only for a user who has _both_ toggles on. It is not an independent loss that occurs in a healthy deploy.
- **Impact / why it fails the bar:** the trigger (the product's own temporal client becoming unimportable at commit time) is practically unreachable in normal operation and, when reachable, is a deploy-wide breakage the on_commit ordering only compounds marginally. This is defensive robustness against a never-gonna-happen edge (guard type per the criteria), not a failure mode that will occur — precision-over-recall says drop. (The `robust=True` suggestion is a cheap, reasonable hardening, but cheapness doesn't lift a practically-unreachable edge over the bar.)

### [❌ dismissed] should_fix · bug — products/tasks/backend/facade/api.py:501-508

**Restrict self-driving matches to active implementation runs**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The branch fallback delegates to `find_task_run`, whose ordinary branch lookup does not exclude terminal or deleted runs. If a self-driving branch name is reused, an unrelated bot PR can match an old completed task run and be treated as a positively identified inbox PR, enabling the webhook carve-out for the wrong task.
- **Suggestion:** Use a dedicated lookup for this facade that filters out terminal and deleted runs, or require an exact PR URL match once a run has recorded one. Do not use stale historical branch runs as proof that the current PR came from a self-driving implementation.
- **Validator:** - **Checked:** `find_signal_implementation_run` → `find_task_run` (`products/tasks/backend/webhooks.py:30-99`), how signals implementation runs set their branch (`products/signals/backend/auto_start.py:269` via `create_and_run_task(..., branch=base_branch)`; `products/tasks/backend/models.py` `create_run`), and the gates in `_inbox_rereview_carve_out`.
- **Found:** signals runs store the BASE branch in the `branch` column (`auto_start.py:269`), not the PR head ref (the agent generates the head branch in-sandbox). So the ordinary branch leg (`filter(branch=head_branch, ...)`, `webhooks.py:69-79`) matches a signals run only if an incoming PR's _head_ ref equals that run's _base_ branch (e.g. a bot PR whose head ref is `master`) — there is no reusable 'self-driving branch name' this leg keys on. The premise of the finding doesn't match how branches are stored.
- **Found:** the pr_url leg (`webhooks.py:42-60`) is the primary, unique matcher; the branch leg is only a pre-URL fallback. And terminal runs are included on purpose — the pr_url leg's comment (`webhooks.py:38-41`) prefers-but-includes terminal runs for same-PR resumes.
- **Found:** the suggested fix (exclude terminal/deleted) would break the intended flow: a signals implementation run reaches COMPLETED as soon as the agent opens the draft PR, yet the still-open PR's later pushes must remain identifiable as self-driving. Excluding terminal runs would drop that common case.
- **Impact:** the described exploit (reused self-driving branch → stale completed run → wrong-task carve-out) is essentially unreachable given base-vs-head branch storage and pr_url precedence; and even a coincidental branch collision is further bounded by the carve-out's prior bot-author + fork-safety + enabled-config gates, so a misidentified PR is at worst a bot-authored, repo-native PR reviewed with stale provenance. Below the bar, and the proposed remedy would regress legitimate re-reviews.
