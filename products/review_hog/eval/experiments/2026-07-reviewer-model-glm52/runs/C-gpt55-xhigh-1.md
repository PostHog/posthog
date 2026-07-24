# Reviewer-quality run — `C-gpt55-xhigh-1`

- **Dumped:** 2026-07-23T23:54:56+00:00
- **Report id:** `019f9122-1671-7715-b230-7d4b3c188cf5`  ·  **PR:** https://github.com/PostHog/posthog/pull/72680
- **Head:** `1341596e721880256a1afb79bbc881364d00e302`  ·  **run_count:** 1  ·  **status:** idle
- **Wall-clock:** 4548s (75.8 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.5` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4 | 7 | 10 | 7 | 0 |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
### Cache-aware spend (local `$ai_generation`, best-effort)

| model | stage | gens | fresh in | cache write | cache read | output | >200K gens | true $ | gw $ |
| ----- | ----- | ---- | -------- | ----------- | ---------- | ------ | ---------- | ------ | ---- |
| gpt-5.5 | review | 125 | 6,704,951 | 0 | 0 | 37,337 | 0 | — | $10.24 |
| claude-opus-4-8 | validation | 72 | 65,094 | 461,606 | 6,680,772 | 62,010 | 0 | $8.10 | $8.10 |
| gpt-5.5 | blind-spot | 42 | 2,323,297 | 0 | 0 | 16,361 | 0 | — | $3.04 |
| claude-sonnet-5 | other:perspective_selection | 1 | 9,029 | 0 | 0 | 1,317 | 0 | $0.03 | $0.03 |
| claude-sonnet-5 | dedup | 1 | 8,947 | 0 | 0 | 576 | 0 | $0.02 | $0.02 |
| **total** |  | **241** | **9,111,318** | **461,606** | **6,680,772** | **117,601** | **0** | **$8.16** | **$21.44** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.5` (167 gen(s), gw $13.28).
- naive method (all prompt tokens at input price): $37.64 — 4.6× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $18.2573 over 241 gen(s) (true $6.5868, Δ +177.2%)
  - · of which cache read: $7.0594 over 224 gen(s) (true $3.3404, Δ +111.3%)
  - · of which cache write: $2.8850 over 72 gen(s) (true $2.8850, Δ +0.0%)
  - · of which fresh (derived): $8.3129 over 241 gen(s) (true $0.3614, Δ +2200.1%)
  - output: $3.1801 over 241 gen(s) (true $1.5692, Δ +102.7%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit | step | first gen | t1 cache read | t1 cache write | models |
| ---- | ---- | --------- | ------------- | -------------- | ------ |
| …43b87b49 | issues-review-p3-c3 | 22:40:16 | 0 | 0 | gpt-5.5 |
| …85a94951 | issues-review-p1-c1 | 22:40:17 | 0 | 0 | gpt-5.5 |
| …29877be3 | issues-review-p3-c2 | 22:40:18 | 0 | 0 | gpt-5.5 |
| …86111420 | issues-review-p3-c1 | 22:40:19 | 0 | 0 | gpt-5.5 |
| …8e8becec | issues-review-p1-c3 | 22:40:24 | 0 | 0 | gpt-5.5 |
| …17e59cb8 | issues-review-p1-c2 | 22:40:28 | 0 | 0 | gpt-5.5 |
| …f92da0d8 | issues-review-p2-c1 | 22:40:30 | 0 | 0 | gpt-5.5 |
| …44e43599 | issues-review-p2-c2 | 22:40:31 | 0 | 0 | gpt-5.5 |
| …d2302dc5 | issues-review-p2-c3 | 22:40:33 | 0 | 0 | gpt-5.5 |
| …b62698aa | issues-review-p1-c2 | 23:10:42 | 0 | 0 | gpt-5.5 |
| …b1eab0e9 | issues-review-p2-c1 | 23:10:43 | 0 | 0 | gpt-5.5 |
| …e0680321 | issues-review-p2-c2 | 23:10:43 | 0 | 0 | gpt-5.5 |
| …ecab5814 | issues-review-p3-c2 | 23:10:43 | 0 | 0 | gpt-5.5 |
| …65558c84 | issues-review-p1-c1 | 23:10:43 | 0 | 0 | gpt-5.5 |
| …df20f692 | issues-review-p1-c3 | 23:10:44 | 0 | 0 | gpt-5.5 |
| …59d3f610 | issues-review-p2-c3 | 23:10:45 | 0 | 0 | gpt-5.5 |
| …9f350965 | issues-review-p3-c1 | 23:10:46 | 0 | 0 | gpt-5.5 |
| …fd0b1da6 | blind-spots-c2 | 23:40:55 | 0 | 0 | gpt-5.5 |
| …9ba65e09 | blind-spots-c3 | 23:40:56 | 0 | 0 | gpt-5.5 |
| …c83195e0 | blind-spots-c1 | 23:40:57 | 0 | 0 | gpt-5.5 |
| …c260c574 | blind-spots-c4 | 23:41:53 | 0 | 0 | gpt-5.5 |
| …059f3f68 | validation-c1 | 23:44:00 | 0 | 39,279 | claude-opus-4-8 |
| …c3afbb10 | validation-c2 | 23:44:00 | 0 | 39,928 | claude-opus-4-8 |
| …3f4d16dc | validation-c3 | 23:44:05 | 17,141 | 21,904 | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **1/24** (report the distribution, not a median).


## Stage timing (wall-clock)

| stage | duration |
| ----- | -------- |
| fetch + snapshot | 0s |
| chunking | 0s |
| perspective selection | 16s |
| review wave (perspectives) | 33m 32s |
| blind-spot sweep | 30m 03s |
| dedup (incl. combine/clean) | 7s |
| validation | 10m 58s |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 63m 35s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective | raw issues |
| ---- | ----- | ----------- | ---------- |
| 1 | 3 | review-hog-perspective-contracts-security | 2 |
| 2 | 3 | review-hog-perspective-logic-correctness | 3 |
| 3 | 3 | review-hog-perspective-performance-reliability | 1 |
| 1000 | 1 | review-hog-blind-spots-general | 1 |
| 1000 | 2 | review-hog-blind-spots-general | 3 |
| 1000 | 3 | ? | 0 |
| 1000 | 4 | ? | 0 |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix · best_practice — tools/pr-approval-agent/review_pr.py:937-938

**Self-driving audit flag is added to the result payload but not to analytics**  
_perspective: review-hog-perspective-logic-correctness  ·  directly-related: True_

- **Problem:** The added audit flag is placed under `to_dict()["classification"]["self_driving"]`, but the review-completed analytics payload in `_capture_review_completed` is unchanged. The PR intent calls out a `stamphog_self_driving_review` stamp on the engine analytics; without adding it to the captured properties, downstream analytics cannot segment relaxed-gate runs from normal reviews.
- **Suggestion:** Add an explicit analytics property in `_capture_review_completed`, e.g. `"stamphog_self_driving_review": self.self_driving`, and keep the existing `to_dict` classification flag if the run output also needs the audit trail.
- **Validator:** - **Checked:** the full PR diff (fetched via `gh pr diff 72680`, since this checkout is pinned at master and the PR head `1341596e` isn't fetchable). Traced how the `self_driving` flag reaches analytics: `_capture_review_completed` (review_pr.py:790-839), `analytics_extra_properties()` (gateway.py:17-32), and the hosted server's env injection in `products/stamphog/backend/temporal/activities.py`.
- **Found:** the stamp is not missing. The PR adds it at `products/stamphog/backend/temporal/activities.py` (`_reviewer_environment`): `extra_properties["stamphog_self_driving_review"] = True` when `run.output["inbox_review"]` is set, serialized into `STAMPHOG_EXTRA_PROPERTIES`. That env var is read by `analytics_extra_properties()` (gateway.py:25) and spread via `**analytics_extra_properties()` into the `stamphog_review_completed` event at review_pr.py:806 (and into the LLM-trace events at reviewer.py:328,354). The PR's own code comment says this is 'so the engine's completed events and LLM traces segment cleanly in analytics,' and `test_integration.py` asserts `STAMPHOG_EXTRA_PROPERTIES["stamphog_self_driving_review"] is True`.
- **Found:** the finding is right that review_pr.py's `_capture_review_completed` was not edited and that `to_dict()["classification"]["self_driving"]` (review_pr.py:934-935 in the diff) is the audit-trail flag — but it wrongly concludes analytics can't segment. Because `stamphog_self_driving_review` is not among the hardcoded base props (which win on collision), it survives the merge and lands on the event.
- **Impact:** none — downstream analytics can already segment relaxed-gate runs from normal reviews. The suggested fix (`"stamphog_self_driving_review": self.self_driving` in `_capture_review_completed`) would be strictly worse: it stamps only the completed event and would miss the LLM-trace events that the current single injection point covers. This is a 'wrong/unreproducible' and 'already handled elsewhere' drop under the criteria.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:1-17

**New migration needs the review_hog max migration marker bumped**  
_perspective: review-hog-blind-spots-general  ·  directly-related: True_

- **Problem:** This adds a new Django migration for the review_hog product, but the chunk does not update `products/review_hog/backend/migrations/max_migration.txt` from `0018_backfill_urgency_threshold_to_consider` to this new `0019_...` migration. Product migration directories in this repo carry that marker for migration numbering/conflict tooling, so leaving it stale can trip preflight/conflict checks and makes the migration directory metadata inconsistent with the actual latest migration.
- **Suggestion:** Update `products/review_hog/backend/migrations/max_migration.txt` to contain `0019_reviewusersettings_stamphog_review_inbox_prs` in the same change as the migration.
- **Validator:** - **Checked:** The PR's full changed-file list (`gh pr view 72680 --json files`) and the actual diff of `products/review_hog/backend/migrations/max_migration.txt`, plus the local migrations directory to establish the pre-PR baseline.
- **Found:** `max_migration.txt` IS in the PR's changed files, and its diff bumps the marker exactly as the suggestion asks: `-0018_backfill_urgency_threshold_to_consider` / `+0019_reviewusersettings_stamphog_review_inbox_prs`. That value matches the new migration filename `0019_reviewusersettings_stamphog_review_inbox_prs.py` precisely.
- **Impact:** The finding's premise is false — the marker is not stale. It only appeared missing because the reviewer saw a partial chunk whose file set (models.py, the 0019 migration, api/settings.py, receivers.py, CodeReviewScene.tsx, generated types) excluded `max_migration.txt`; the file is bumped elsewhere in the same PR. No preflight/conflict-tooling breakage exists. This is a 'wrong / unreproducible' drop under the validation bar.

### [❌ dismissed] must_fix · security — products/stamphog/backend/tasks/tasks.py:1107-1173

**Inbox review task trusts caller-supplied provenance without revalidating the TaskRun**  
_perspective: review-hog-blind-spots-general  ·  directly-related: True_

- **Problem:** `process_inbox_pr_review` accepts `team_id`, `pr_url`, `signal_report_id`, `task_run_id`, and `acting_user_id` from the caller, then stamps `output.inbox_review` and starts a self-driving review after only checking that the PR belongs to a synced Stamphog repo. Unlike the webhook carve-out, this path does not independently verify that the task run exists for the same team, is non-internal, carries the supplied signal report, and actually produced this PR URL. If the receiver is ever called with stale or incorrect task output, or another internal caller uses the facade incorrectly, Stamphog can bypass the normal bot/draft/review-mode/write-permission gates for an arbitrary PR in a configured repo.
- **Suggestion:** Before creating the `ReviewRun`, resolve the task through the tasks facade by `task_run_id` and `team_id` and verify the run is the expected self-driving shape: same team, non-internal task, matching `signal_report_id`, and matching PR URL/repository/head branch. Alternatively add a dedicated tasks facade method for this exact receiver-leg validation and fail closed if it returns `None`. Only stamp `output["inbox_review"]` after that check passes.
- **Validator:** - **Checked:** Traced every caller of `process_inbox_pr_review` and `queue_inbox_pr_review` across the PR diff, plus `handle_task_run_saved` (products/review_hog/backend/receivers.py) and `find_signal_implementation_run` (products/tasks/backend/facade/api.py).
- **Found:** The task is only reachable via `queue_inbox_pr_review.delay()` (diff L708), whose only caller is review_hog's `_start_stamphog_review` (diff L279), invoked solely from `handle_task_run_saved`. That receiver derives all five params directly from the just-saved `TaskRun` instance — `pr_url = instance.output['pr_url']`, `task_run_id = str(instance.id)`, `signal_report_id = str(task.signal_report_id)`, `team_id = instance.team_id` (diff L127-146) — after already enforcing `task.signal_report_id is not None`, `not task.internal`, and status ∉ {FAILED, CANCELLED} (receivers.py L84-90). The linkage the finding wants re-verified is established by construction at the call site.
- **Found:** The webhook↔receiver asymmetry is deliberate, not an oversight. The webhook leg calls `find_signal_implementation_run` because GitHub delivers events for arbitrary PRs and has no trustworthy linkage — it resolves the run *from* the PR URL. The receiver leg is driven by the TaskRun itself, so it already holds a verified, in-hand run. Re-running `find_signal_implementation_run(team_id, pr_url=...)` would resolve the same run from the same pr_url and pass trivially, adding no protection against the real caller — and it would not catch a hypothetically wrong-but-self-consistent pr_url either.
- **Impact:** The named triggers don't meet the bar. 'Stale output' is already handled (fresh GitHub fetch, open-state check, stale-snapshot guard under row lock, head-keyed dedupe — diff L1078-1140). 'Incorrect output' requires the internal agent-server/webhook-backstop to write a wrong pr_url — an upstream concern shared with the pre-existing ReviewHog `_start_review` leg and unfixed by the suggestion. 'Another internal caller misusing the facade' is a speculative future bug, not a reachable condition given the sole call site. This is defense-in-depth / redundant re-validation a trusted parent caller already performs, so per precision-over-recall it is dropped.

### [❌ dismissed] should_fix — products/tasks/backend/facade/api.py:503-511

**Team scoping is applied after an unscoped task lookup, causing false negatives**  
_perspective: review-hog-blind-spots-general  ·  directly-related: True_

- **Problem:** `find_signal_implementation_run` delegates to `find_task_run` without passing `team_id`, then discards the result if it belongs to another team. Because `find_task_run` returns only the first matching run for a PR URL or repository/branch, a matching run from another team can mask the correct same-team run and make the Stamphog webhook carve-out fail closed. This is especially likely for repository/branch fallback, where branch names can collide across teams working in the same repository.
- **Suggestion:** Make the lookup team-scoped before selecting a row. For example, add a team-scoped variant of `find_task_run`, or implement this facade query directly with `TaskRun.objects.filter(team_id=team_id, ...)` for both the PR URL and repository/branch legs before applying the signal/internal checks.
- **Validator:** - **Checked:** `find_task_run` (products/tasks/backend/webhooks.py:30-99), the carve-out call site `_inbox_rereview_carve_out` (diff L862-914), and how `pr_url` reaches the lookup; also whether signals implementation tasks are wizard runs.
- **Found:** The carve-out always passes `pr_url=pr.get("html_url")` from a `pull_request` webhook (diff L909-914). `find_task_run` runs the pr_url leg first and returns on match (webhooks.py:37-58); the branch fallback (webhooks.py:61+) is only consulted when the pr_url leg yields nothing. So the issue's headline case — cross-team branch-name collision — is behind a leg that the always-present pr_url normally skips.
- **Found:** A GitHub PR URL is globally unique to one PR/repo, and each self-driving PR is opened by exactly one run; the only same-pr_url collisions are same-team resumes (documented at webhooks.py:38-40). No other-team run carries the same pr_url, so the pr_url leg resolves the correct same-team run — cross-team masking there is unreachable, not merely rare.
- **Found:** Reaching the branch fallback requires the opening run to not yet have recorded `output.pr_url`. But recording pr_url is what triggers the initial receiver-leg review, and the carve-out scope is later deliveries only (synchronize/reopen/retarget), by which point pr_url is recorded. On top of that, masking would need two teams running tasks with identical generated (`posthog-code/…`) branch names in one shared repo.
- **Impact:** Even in that theoretical race the outcome is a skipped re-review (fail-closed), not a tenant-isolation violation — the team check returns None on mismatch and never binds a PR to another team's run (diff L917-918), and the initial draft-time verdict already posted. A practically-unreachable edge case with a low, safe consequence does not meet the bar; per precision-over-recall, drop.

### [❌ dismissed] should_fix · best_practice — products/stamphog/backend/facade/api.py:151-157

**Fire-and-forget facade can still raise broker errors into the caller**  
_perspective: review-hog-blind-spots-general  ·  directly-related: True_

- **Problem:** `queue_inbox_pr_review` is documented as fire-and-forget so the caller's save path never blocks on the Stamphog leg, but `process_inbox_pr_review.delay(...)` can raise when the Celery broker is unavailable or serialization fails. If the review_hog receiver does not catch this at every call site, a transient queueing failure can bubble into the TaskRun save path and break the primary self-driving task flow.
- **Suggestion:** Wrap the `.delay(...)` call in a broad exception handler, log enough context to debug the missed Stamphog enqueue, and return without raising. If callers should own that behavior instead, narrow the facade docstring and ensure every caller catches broker failures explicitly.
- **Validator:** - **Checked:** The facade `queue_inbox_pr_review` (products/stamphog/backend/facade/api.py, diff L687-713), its only production caller in review_hog, and the broker-failure test coverage; grepped all call sites of `queue_inbox_pr_review`.
- **Found:** The facade does not wrap `.delay()` (diff L708-713), but the sole production caller `_start_stamphog_review` (products/review_hog/backend/receivers.py, diff L206-228) already wraps the call in `try/except Exception` + `logger.exception('review_hog_stamphog_inbox_review_queue_failed')`; its docstring states 'the broker being down must never surface into the saver.' Grep shows exactly one production call site (diff L279) — 'every call site' is that one guarded site.
- **Found:** `test_stamphog_queue_failure_never_raises_into_the_save_path` (diff L365-376) patches the facade with `side_effect=RuntimeError('broker down')` and asserts the TaskRun output save 'must not raise' — the precise failure mode the finding hypothesizes is already regression-tested.
- **Found:** The caller is dispatched via `transaction.on_commit(...)` in `handle_task_run_saved` (diff L138-146), so it runs after the TaskRun commit; even an unhandled raise could not roll back the save or break the primary task flow.
- **Impact:** The premise ('if the receiver does not catch this') is false — it does, at its only call site, with a test, and post-commit. The suggestion is a redundant try/except (defensive paranoia) and a docstring nit for behavior that is already correct and owned by the caller. Does not meet the bar; drop.

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:316-321

**Privileged self-driving flag is parsed with loose truthiness**  
_perspective: review-hog-perspective-contracts-security  ·  directly-related: True_

- **Problem:** The hosted sandbox entrypoint enables the bot/draft gate carve-out with `bool(context.get("self_driving_review"))`. That treats any non-empty value as privileged, including strings like `"false"`, `"0"`, or other malformed JSON values. Because this flag relaxes security-sensitive gates, the contract should fail closed unless the server provided the exact boolean `true`.
- **Suggestion:** Parse the flag strictly, for example `self_driving = context.get("self_driving_review") is True`, and optionally reject/log non-boolean values so malformed context cannot accidentally enable the carve-out.
- **Validator:** - **Checked:** the end-to-end flow of `self_driving_review`. Engine side, `review_local.py:391` loads the context via `json.loads(Path(args.context).read_text())`, then `run()` (diff line 1937) does `Pipeline(..., self_driving=bool(context.get("self_driving_review")))`. Producer side, the context file is written only by trusted server code.
- **Found:** the value is always a JSON boolean or absent — never a string. `products/stamphog/backend/logic/reviewer.py::build_reviewer_invocation` declares `self_driving_review: bool = False` (typed `bool`) and writes `context["self_driving_review"] = self_driving_review`; its caller `products/stamphog/backend/temporal/activities.py` passes `bool(output.get("inbox_review"))`. A Python `bool` serializes to JSON `true`/`false` and deserializes back to a `bool`, so `context.get("self_driving_review")` is only ever `True`, `False`, or `None` — for all of which `bool(x)` equals `x is True`.
- **Found:** no untrusted input reaches this field. It derives from `run.output["inbox_review"]` (server-stamped inbox provenance), not from the reviewed PR's author/diff/metadata; the Action runtime never sets it (absent → `False`). The hypothesized `"false"`/`"0"` string would require the trusted server to violate its own `bool` contract, or a developer to hand-author a malformed `--context` file — manual misuse, not a security boundary.
- **Impact:** none reachable. The loose-vs-strict truthiness distinction is unobservable given the upstream `bool` type and server-controlled context source. This is a speculative 'what if' / defensive-coding-paranoia drop under the criteria, and the `must_fix` security severity is unwarranted because there is no untrusted-input path and no user-affecting consequence.

### [❌ dismissed] must_fix · bug — tools/pr-approval-agent/reviewer.py:568-568,683-703

**Self-driving prompt can still include author familiarity context**  
_perspective: review-hog-perspective-logic-correctness  ·  directly-related: True_

- **Problem:** The new provenance block is appended after the existing familiarity block, but nothing in this chunk guarantees familiarity is absent for `self_driving` runs. If `classification["familiarity"]` is populated by `Pipeline._maybe_compute_familiarity()` or by the offline context path, the prompt will contain both human-author familiarity and the new machine-author provenance guidance, contradicting the stated invariant that provenance replaces human-author trust signals for self-driving PRs.
- **Suggestion:** Make the invariant explicit in code: skip familiarity computation/attachment when `pipeline.self_driving` is true in both `review_pr.py` and `review_local.py`, or have `_format_familiarity` return `""` when `cl.get("self_driving")` is true. Add a regression test where `self_driving` and a populated familiarity object are both present and the prompt contains only the provenance block.
- **Validator:** - **Checked:** which entrypoint ever sets `self_driving`, and whether familiarity can be populated on the same run. Only `review_local.py` (hosted sandbox) reads `self_driving` from context; `review_pr.py`/Action leaves it `False` by default. Traced `review_local.py::_attach_familiarity`, `reviewer.py::_format_familiarity`, and the server source of `author_pr_numbers`.
- **Found:** for a self-driving run the familiarity block is guaranteed empty, so the two blocks cannot coexist. `_attach_familiarity` (`review_local.py:299-303`) early-returns unless tier is `T1-agent` AND `context["author_pr_numbers"]` is truthy; on that path `classification["familiarity"]` stays `None`, and `_format_familiarity` returns `""` when `fam is None` (`reviewer.py:644-645`), so no familiarity text is appended.
- **Found:** the hosted server couples both signals to one provenance flag so they cannot diverge. In `products/stamphog/backend/temporal/activities.py`, `fetch_review_context` sets `author_pr_numbers = []` when `is_inbox_review` (diff 1215-1216) and `run_review_in_sandbox` passes `self_driving_review=bool(output.get("inbox_review"))` (diff 1227) — both from `run.output["inbox_review"]`. Hence `self_driving=True ⟺ inbox review ⟺ author_pr_numbers=[]`, forcing familiarity absent; `test_integration.py` asserts no author merged-PR history is fetched for the inbox leg.
- **Impact:** none reachable — the predicted prompt contradiction (both familiarity and provenance) cannot occur in current code. The invariant is enforced by the coupled server logic plus the engine's tier/PR-numbers gate, so this is an 'already handled elsewhere' / 'speculative what-if ruled out by the call sites' drop, and the suggested extra guard is defensive paranoia. `must_fix` is unwarranted absent any reachable defect.

