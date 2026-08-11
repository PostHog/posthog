# Reviewer-quality run — `J-gpt56sol-seq-1`

- **Dumped:** 2026-07-31T08:30:39+00:00
- **Report id:** `019fb731-4834-71f4-8863-7010a1f5831d` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1727s (28.8 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 11         | 10          | 3                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read    | output      | >200K gens | true $    | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | ------------- | ----------- | ---------- | --------- | ---------- |
| claude-opus-4-8 | validation                  | 74      | 68,272        | 400,852     | 7,541,147     | 115,925     | 2          | $9.52     | $9.52      |
| gpt-5.6-sol     | review                      | 74      | 3,779,588     | 0           | 0             | 20,577      | 0          | —         | $5.46      |
| gpt-5.6-sol     | blind-spot                  | 27      | 1,260,214     | 0           | 0             | 5,857       | 0          | —         | $1.86      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0             | 1,354       | 0          | $0.03     | $0.03      |
| claude-sonnet-5 | dedup                       | 1       | 5,689         | 0           | 0             | 399         | 0          | $0.02     | $0.02      |
| **total**       |                             | **177** | **5,119,744** | **400,852** | **7,541,147** | **144,112** | **2**      | **$9.56** | **$16.87** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.6-sol` (101 gen(s), gw $7.32).
- naive method (all prompt tokens at input price): $42.99 — 4.5× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $13.1657 over 177 gen(s) (true $6.6406, Δ +98.3%)
  - · of which cache read: $5.8455 over 159 gen(s) (true $3.7706, Δ +55.0%)
  - · of which cache write: $2.5053 over 74 gen(s) (true $2.5053, Δ -0.0%)
  - · of which fresh (derived): $4.8149 over 177 gen(s) (true $0.3647, Δ +1220.2%)
  - output: $3.7087 over 177 gen(s) (true $2.9157, Δ +27.2%)
- 2 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …fb6d2f83 | issues-review-p3-c1 | 08:02:41  | 0             | 0              | gpt-5.6-sol     |
| …1acb40b2 | issues-review-p3-c2 | 08:02:41  | 0             | 0              | gpt-5.6-sol     |
| …0c1ae487 | issues-review-p2-c2 | 08:02:41  | 0             | 0              | gpt-5.6-sol     |
| …6c9f0016 | issues-review-p1-c2 | 08:02:43  | 0             | 0              | gpt-5.6-sol     |
| …b153fc1a | issues-review-p1-c3 | 08:02:43  | 0             | 0              | gpt-5.6-sol     |
| …09226501 | issues-review-p2-c1 | 08:02:43  | 0             | 0              | gpt-5.6-sol     |
| …036de04d | issues-review-p2-c3 | 08:02:43  | 0             | 0              | gpt-5.6-sol     |
| …62801e4a | issues-review-p1-c1 | 08:02:46  | 0             | 0              | gpt-5.6-sol     |
| …7e37c220 | issues-review-p2-c2 | 08:05:37  | 0             | 0              | gpt-5.6-sol     |
| …53a07e65 | issues-review-p1-c1 | 08:05:37  | 0             | 0              | gpt-5.6-sol     |
| …63abd79e | blind-spots-c1      | 08:07:41  | 0             | 0              | gpt-5.6-sol     |
| …742dda3c | blind-spots-c2      | 08:07:41  | 0             | 0              | gpt-5.6-sol     |
| …42a618eb | blind-spots-c4      | 08:07:42  | 0             | 0              | gpt-5.6-sol     |
| …61e1b455 | blind-spots-c3      | 08:07:44  | 0             | 0              | gpt-5.6-sol     |
| …bd2c5c1a | validation-c2       | 08:09:31  | 0             | 37,944         | claude-opus-4-8 |
| …bb00da88 | validation-c3       | 08:09:32  | 17,141        | 19,982         | claude-opus-4-8 |
| …247b0b12 | validation-c1       | 08:09:36  | 17,141        | 20,570         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **2/17** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 16s      |
| review wave (perspectives)  | 5m 04s   |
| blind-spot sweep            | 1m 55s   |
| dedup (incl. combine/clean) | 5s       |
| validation                  | 21m 22s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 6m 59s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                                    | raw issues |
| ---- | ----- | ---------------------------------------------- | ---------- |
| 1    | 1     | ?                                              | 0          |
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] should_fix · security — products/stamphog/backend/tasks/tasks.py:113-120

**PR URL parsing accepts embedded GitHub-looking substrings from arbitrary hosts**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `_PR_URL_RE.search()` is not anchored to an HTTPS GitHub URL or hostname boundary. Values such as `https://attacker.example/github.com/org/repo/pull/123` are accepted and converted into a request for the real `org/repo#123`. Since this value feeds the privileged inbox-review path, malformed or attacker-influenced task output can select a different review target than the URL represents.
- **Suggestion:** Parse the URL with `urllib.parse.urlparse`, require `scheme == "https"` and `hostname == "github.com"` (or an explicitly supported allowlist), and validate the path as exactly `/<owner>/<repo>/pull/<positive integer>` with no credentials, unexpected port, or extra target-changing components.
- **Validator:** - **Checked:** Traced `_parse_pr_url` (PR-head `products/stamphog/backend/tasks/tasks.py:116`) and its sole non-test caller `process_inbox_pr_review` (`tasks.py:1110`); traced `pr_url` back through `queue_inbox_pr_review` (`facade/api.py:128`) to review_hog's `handle_task_run_saved`/`_start_stamphog_review` (`receivers.py`), where it is `TaskRun.output["pr_url"]`; checked every downstream use of the parsed `(owner/repo, number)`.
- **Found:** The parsed tuple only resolves a `team_id`-scoped `StamphogRepoConfig` filtered `enabled=True`, non-blank `installation_id`, `connected_by_user_id` set, `repository__iexact=<owner/repo>` (`tasks.py:1139-1148`); the subsequent GitHub fetch uses `repo_config.repository` and `repo_config.installation_id` from the DB (`tasks.py:1160`). The URL's scheme/host/port are never used for any request — so a spoofed `attacker.example/github.com/...` host yields the exact same extracted target as a clean URL and changes nothing downstream.
- **Found:** The suggested fix does not close the stated "select a different review target" threat. Redirection is achievable by an actor controlling `pr_url` with a perfectly anchored `https://github.com/<target>/pull/N`; requiring `hostname == "github.com"` only rejects a malformed substring form no real attacker needs. The actual missing control on the receiver leg is positive run-linkage identification — which the webhook carve-out already performs via `find_signal_implementation_run` (`products/tasks/backend/facade/api.py:484`) — not URL host anchoring.
- **Impact:** For all legitimate inputs the leftmost-match regex extracts correctly, so there is no correctness bug; the target is bounded to the team's own enabled+synced Stamphog repos; and the proposed anchoring provides no security benefit against the described redirection. This is minor input-hardening/consistency polish (matching `_is_github_pull_request_url_for_repository`), not a reachable security defect — below the keep bar (speculative/wrong-premise).

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:316-324

**Fail closed when parsing the gate-bypass flag**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool(context.get("self_driving_review"))` enables the self-driving carve-out for any truthy JSON value, including strings such as `"false"`, numbers, or objects. This flag bypasses the bot-author refusal and draft prerequisite and injects trusted provenance into the reviewer prompt, so malformed context can unintentionally authorize a review under relaxed gates.
- **Suggestion:** Require the exact JSON boolean `true`, for example `self_driving = context.get("self_driving_review") is True`, and reject or default closed for every other type. Consider also asserting that the resulting PR is bot-authored before retaining the flag, so the trusted machine-author claim and draft bypass cannot diverge from `PRData`.
- **Validator:** - **Checked:** The full producer→consumer chain for `self_driving_review`: `build_reviewer_invocation` (reviewer.py `+787`) which writes the context dict, its sole hosted caller `run_review_in_sandbox` (tasks.py `+1227`), the JSON round-trip into the sandbox, and both engine entrypoints (`review_local.py` `run()` and the Action's `review_pr.py`).
- **Found:** The flag is set exclusively via `self_driving_review=bool(output.get("inbox_review"))` (tasks.py `+1227`) — already a genuine Python `bool` — and `build_reviewer_invocation` places that bool into the context dict (`+787`), which is JSON-serialized to the sandbox context file. The end-to-end test confirms the on-disk value is a real JSON boolean: `assert context["self_driving_review"] is True` (test_integration `+1287`). The Action path never sets the key, so `context.get(...)` is `None`. Thus `context.get("self_driving_review")` is only ever `True`, `False`, or absent — and `bool(True) is True → True`, `bool(False) → False`, `bool(None) → False`, identical to the suggested `is True`.
- **Impact:** The premise — a truthy string/number/object slipping through — cannot be reached: the upstream `bool(...)` invariant guarantees a genuine boolean, and the context is a trusted server artifact rather than attacker-writable JSON. This is defensive hardening against an input the call-site invariant already rules out. It also yields no security benefit under the only model where parsing would matter (an attacker who can overwrite the context file would just write `true`), so the change is behaviorally a no-op for every reachable input. Falls under speculative 'what if' / defensive-coding paranoia in the drop criteria.

### [✅ VALID] must_fix (validator→should_fix) · bug — products/review_hog/backend/receivers.py:111-135,144-160

**Stamphog gate checks only one assignee instead of any opted-in assignee**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** Both the initial trigger and webhook resolver select one canonical acting reviewer, then inspect only that user's `stamphog_review_inbox_prs` setting. If that reviewer is opted out while another assigned reviewer is opted in, no Stamphog review runs. This contradicts the stated requirement that a review run when at least one assigned user has enabled the toggle, and turning off one user's toggle can incorrectly stop later re-reviews despite another assignee remaining opted in.
- **Suggestion:** Resolve the complete ordered set of assigned organization users for the Stamphog path, select an opted-in user with `next((user for user in resolved if ReviewUserSettings.load(team_id, user.id).stamphog_review_inbox_prs), None)`, and return that user's ID. Preserve the existing single acting-reviewer selection separately for ReviewHog, whose configuration is intentionally tied to the task creator or primary assignee. Use the same any-opted-in resolver for both initial dispatch and webhook rechecks.
- **Validator:** - **Checked:** the full receivers.py PR diff — `_resolve_assigned_reviewer`, the initial trigger in `handle_task_run_saved`, the webhook re-check `resolve_stamphog_acting_reviewer`, and the `inbox_hooks` registry that stamphog's webhook task calls through.
- **Found:** `_resolve_assigned_reviewer` collapses to ONE acting reviewer — `acting = next((user for user in resolved if user.id == task_created_by_id), resolved[0])` (receivers.py ~L204) — and both legs gate on only that user: the trigger does `if pr_url is not None and settings.stamphog_review_inbox_prs:` where `settings = ReviewUserSettings.load(team_id, acting_user_id)`, and `resolve_stamphog_acting_reviewer` re-derives the same single acting id then checks only its toggle. No path iterates the resolved set for any opted-in user.
- **Found:** for a fully auto-started self-driving PR, `created_by` is the GitHub-integration bot (per the module docstring) and is not in the resolved set, so the acting reviewer is `resolved[0]` — the first suggested reviewer by artefact order. If `resolved[0]` is opted out of stamphog while a later assignee is opted in, no stamphog review is queued; and on a later push, if `resolved[0]` toggles off, `resolve_stamphog_acting_reviewer` returns None and re-reviews stop even though another assignee remains opted in.
- **Found:** the PR body states the gate three times as any-opted-in — "any assigned reviewer opted in" (Case 1), "at least one of the assigned users has `stamphog_review_inbox_prs` enabled", "nobody is opted in, so no review runs" (Case 3). The implementation checks exactly one, so it diverges from the feature's own stated central behavior. Architecturally this fits: ReviewHog needs the single-acting collapse to pick ONE user's perspectives/urgency config to drive the review, but stamphog's toggle is a binary gate with no per-user options, so reusing the single-acting resolver for it silently ignores other assignees' opt-in.
- **Impact:** realistic multi-reviewer reports (differing per-user opt-in, default-off) hit this; stamphog reviews are skipped for cases the stated design says should run, and one user toggling off can halt re-reviews despite another remaining opted in. Concrete trigger + concrete consequence, directly in the code this PR adds.
- **Priority:** lowering must_fix → should_fix. The failure mode is fail-safe (a skipped review, never a wrong GitHub approval), the feature is explicitly experimental (draft PR, `experiment-frozen` branch), and the code docstring deliberately describes single-acting-reviewer gating both toggles — so there is a defensible intentional-design reading. The divergence from the stated any-opted-in requirement is real and worth resolving, but not the severity of a data-loss/security/wrong-approval defect.

### [❌ dismissed] should_fix · bug — products/tasks/backend/facade/api.py:506-512

**Team and self-driving filters are applied after selecting an arbitrary run**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** find_task_run searches globally and selects one matching run before this facade checks team_id, signal_report_id, and task.internal. Multiple runs can legitimately share a PR URL or repository/branch, including resumed runs, another team's run, or an unrelated/internal task. If find_task_run selects one of those, this function returns None even when a qualifying self-driving run exists, causing valid inbox re-reviews to be skipped. The branch lookup also uses an unordered first(), making the result unstable when several runs match.
- **Suggestion:** Move team_id and the self-driving task predicates into the queryset used to select the run, and retain the existing active/newest ordering for PR URL matches. Prefer extending find_task_run with explicit filters or implementing a facade-specific scoped query so selection occurs only among eligible candidates.
- **Validator:** - **Checked:** Read `find_task_run` (`products/tasks/backend/webhooks.py:29-98`), `find_signal_implementation_run` (`products/tasks/backend/facade/api.py:484-517`), the carve-out call site (`products/stamphog/backend/tasks/tasks.py:191`), and the run-provenance invariants in `products/review_hog/backend/receivers.py`.
- **Found (internal-task masking ruled out):** Internal plumbing tasks cannot mask a qualifying run — `receivers.py` documents that report-research / repo-selection / custom-agent tasks are `internal=True` and _push nothing_, so they never populate `output.pr_url` or a PR head branch and therefore never match `output__pr_url=pr_url` or `branch=head_branch`. The `task.internal` post-filter has no colliding candidate to lose to.
- **Found (cross-team masking not reachable):** The `pr_url` leg keys on `output__pr_url=pr_url` (`webhooks.py:41`). A specific GitHub PR is opened by exactly one run lineage, so its URL is unique; two teams sharing repo `org/repo` open _different_ PR numbers → different URLs → no shared `output__pr_url`. Even if `find_task_run` returned a foreign-team run, the team post-filter (`api.py:505`) fails **closed** (returns None), and the carve-out re-checks it (`tasks.py:199`), so there is no tenant leak — at most a missed round.
- **Found (resumes handled):** The documented multi-run-per-URL case (terminal original + live resume, `webhooks.py:37-39`) is same-team/same-signal-lineage, so both candidates pass the post-filters, and the ordering `terminal_rank, -created_at` already picks the live one.
- **Found (branch-leg `first()`):** The unordered `.first()` (`webhooks.py:69`) is pre-existing webhook-backstop behavior, not introduced by this PR; the carve-out always passes `pr.html_url` and self-driving runs record their pr_url, so the ordered pr_url leg resolves them and the branch leg is not the resolving path here.
- **Impact:** No realistic input produces the claimed "qualifying self-driving run masked by a non-qualifying one" skip. Worst residual is a rare missed re-review that a subsequent delivery re-triggers, and the caller's head-changing retraction still dismisses stale approvals — the stale-approval safety invariant is not preference- or timing-gated. Speculative collision scenario, below the correctness bar.

### [❌ dismissed] should_fix · bug — tools/pr-approval-agent/reviewer.py:568-568

**Self-driving reviews still include bot-author familiarity**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The prompt concatenates both `familiarity_block` and `self_driving_block`. Hosted execution still calls `_attach_familiarity`, and the server fetches merged PR numbers for the bot author, so a bot with prior merged PRs can receive a positive human-author familiarity signal. This contradicts the new provenance block and can incorrectly influence the verdict.
- **Suggestion:** Skip familiarity computation for self-driving runs and defensively omit `familiarity_block` when `cl["self_driving"]` is true.
- **Validator:** - **Checked:** The full familiarity data path for a self-driving run: the server-side context builder (`fetch_review_context` in tasks.py `+1210-1216`), the engine's `_attach_familiarity` (review_local.py, unchanged `if not raw_prs: return` at lines 301-303), and `_format_familiarity` (reviewer.py:643-645), plus whether `author_pr_numbers` and `self_driving_review` can diverge.
- **Found:** The issue's core premise — 'the server fetches merged PR numbers for the bot author' — is false. The companion change in this same PR does the opposite: `is_inbox_review = bool((run.output or {}).get("inbox_review"))` and `author_pr_numbers = client.get_author_merged_pr_numbers(...) if author and not is_inbox_review else []` (tasks.py `+1215-1216`). For inbox/self-driving runs the fetch is skipped and `author_pr_numbers` is `[]` — the end-to-end test even asserts `context["author_pr_numbers"] == []` (test_integration `+1289`).
- **Found:** With empty `author_pr_numbers`, `_attach_familiarity` hits `raw_prs = context.get("author_pr_numbers")` → `if not raw_prs: return` (review_local.py:301-303), so `cl["familiarity"]` is never populated. `_format_familiarity` then returns `""` because `fam is None` (reviewer.py:643-645). So `familiarity_block` is empty precisely when `self_driving_block` renders.
- **Found:** The two flags cannot diverge — both derive from the same `run.output["inbox_review"]` provenance (`self_driving_review=bool(output.get("inbox_review"))` at tasks.py `+1227`; `author_pr_numbers` gate at `+1215`), stamped once at trigger time before either activity reads it.
- **Impact:** The described failure (a bot receiving a positive human-author familiarity signal alongside the provenance block) is unreachable: whenever `cl["self_driving"]` is true, familiarity is already absent by construction. The suggested guard would be dead code. Falls under 'wrong / unreproducible' and 'already handled elsewhere' in the drop criteria.

### [✅ VALID] should_fix (validator→consider) · code_quality — tools/pr-approval-agent/reviewer.py:697-699

**Provenance prompt falsely states every self-driving PR is a draft**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The self-driving flag identifies task provenance, not current draft state, but the trusted prompt always says the PR is a draft and that draft state should be ignored. A later push can trigger another review after the PR becomes ready, making this trusted statement factually wrong.
- **Suggestion:** Pass `pr.draft` into the formatter and include the draft-specific guidance only when it is true, or phrase it conditionally without asserting the current state.
- **Validator:** - **Checked:** `_format_self_driving` (reviewer.py `+697-699`), and every path that sets the `inbox_review`/`self_driving` provenance that gates the block: the webhook re-review carve-out `_inbox_rereview_carve_out` and skip flow in tasks.py (`+862-933`, `+956-966`), and the receiver leg `process_inbox_pr_review` (`+1097-1160`). I looked specifically for a `pr.draft` guard on these paths.
- **Found:** The block hardcodes 'It is a draft on purpose ... draft state is not a caution signal for this PR' with no conditioning on actual draft state (reviewer.py `+697-699`). Neither provenance-setting path requires the PR to still be a draft: `_inbox_rereview_carve_out` gates only on head-changing action, bot authorship, repo-native head, config, task linkage, and opt-in — no draft check (`+885-933`); the receiver leg gates on `state == "open"` only, explicitly not draft (`+1097-1100`). `_review_skip_reason` returns `bot_author` for a non-draft bot PR (`+940-947`), so a self-driving PR that flipped to ready and then receives a `synchronize` still enters the carve-out and renders the block. This is a plausible workflow (a triaged draft marked ready, then a follow-up push), not a contrived one.
- **Impact:** The trusted context fed to the review LLM can state a false premise about the PR's lifecycle. Confirmed reachable, so not wrong/unreproducible — a genuine accuracy defect worth a cheap conditional fix.
- **Priority:** Lowering should_fix → consider. The reviewer's stated harm ('can incorrectly influence the verdict') is weaker than claimed: the block's only actionable instruction ('draft state is not a caution signal') is inert when there is no draft, and the sibling sentence 'judge the diff strictly on its own merits' counteracts any leniency the false 'draft on purpose' framing might induce. Reachable only in an edge case with no concrete wrong-verdict mechanism — real but minor.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:222-234

**Persist or retry failed Stamphog dispatches**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The post-commit callback catches every exception from `queue_inbox_pr_review` and only logs it. Because the TaskRun transaction has already committed and no durable retry marker is recorded, an exhausted broker publish failure permanently drops the initial Stamphog review unless an unrelated later save happens to retrigger the receiver.
- **Suggestion:** Dispatch through a durable outbox/retry mechanism, or persist pending dispatch state keyed by the task run and have a retrying worker enqueue it. Keep the save path isolated, but ensure a transient broker outage cannot silently lose the review.
- **Validator:** - **Checked:** `_start_stamphog_review` in the PR diff, the pre-existing `_start_review` (ReviewHog) leg it mirrors, the module-level docstring on re-trigger semantics (receivers.py L59-63), and the `queue_inbox_pr_review` facade behavior.
- **Found:** the catch is `except Exception: logger.exception("review_hog_stamphog_inbox_review_queue_failed")` — the failure is logged at exception level, not hidden. Both the docstring ("the broker being down must never surface into the saver") and the identical, already-accepted pattern on the ReviewHog `_start_review` leg show this swallow-and-log is a deliberate, documented convention for this file, which runs inside the tasks save path and must never raise into it. This is not a new defect introduced by the change.
- **Found:** the dispatch is a Celery broker publish (`queue_inbox_pr_review` "queues a Celery task, so the only work on this save path is the broker publish"); the only loss scenario is a rare transient broker outage at the exact on-commit moment. Recovery paths already exist: receivers.py L61-63 states repeat TaskRun saves with an unchanged target deliberately re-fire the receiver (re-dispatching the stamphog leg while the toggle is on), and PR Case 2 re-reviews via stamphog's webhook path on the next push — the finding itself concedes a later save retriggers it.
- **Impact:** the suggested remedy (a durable outbox / persisted pending-dispatch state + a retrying worker) is a substantial reliability subsystem for a best-effort, fail-safe (no wrong approval — only a possibly-delayed review), explicitly experimental feature that already has natural re-trigger paths. That is the 'add an abstraction / future-proof for a case not in scope' shape the criteria drops as overengineering, and it would apply equally to the long-standing ReviewHog leg it mirrors. It does not clear the bar of a reliability defect that will realistically bite.

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:1158-1183

**Inbox provenance is granted without verifying the PR belongs to the task run**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The initial-review task accepts `pr_url`, `acting_user_id`, `signal_report_id`, and `task_run_id` from its caller, but after fetching the PR it only checks that the PR is open and has a head SHA. It never verifies that `task_run_id` belongs to `team_id`, carries `signal_report_id`, targets this repository and head branch, or that the PR is repo-native and bot-authored. Nevertheless, it stamps `inbox_review`, which later enables the privileged engine path that bypasses bot, draft, review-mode, and author-permission gates. Because task output containing the PR URL can originate from an agent run, a mistaken or manipulated URL could cause an unrelated PR in any configured repository for the team to receive this privileged review and potentially an approval.
- **Suggestion:** Before creating the run, load the supplied task run through a team-scoped facade and require its task to be the expected non-internal signal implementation with the supplied signal report. Compare the fetched PR's repository and head branch against that run, require `head.repo.full_name` to equal the base repository, and verify the expected GitHub App bot identity. Derive the provenance fields from the verified DTO rather than trusting the Celery arguments. Apply the same verified binding to webhook re-reviews instead of treating a task's stored `pr_url` alone as proof of origin.
- **Validator:** - **Checked:** Traced the receiver leg `process_inbox_pr_review` (tasks.py:1130-1183) vs. the webhook carve-out `_inbox_rereview_carve_out` (tasks.py:144-215); the provenance→engine flow (`activities.py:451` sets `self_driving_review` from `output['inbox_review']`); and the engine gates (`tools/pr-approval-agent/review_pr.py:225,590`, `gates.py`).
- **Found (real asymmetry):** The carve-out gates provenance on `_is_bot_authored(pr)` AND repo-native `head_repo == repo` (fork-safety) AND a `find_signal_implementation_run` facade match. The receiver leg stamps the _same_ `inbox_review` provenance after checking only `state == 'open'` and a non-empty `head_sha` — no bot-author, no repo-native/fork, no run re-binding.
- **Found (no compensating gate downstream):** The engine has no fork or author-association gate; `self_driving=True` relaxes exactly the bot-author refusal and the draft prerequisite (`review_pr.py:225,590`). Fork/association filtering lives only in the webhook pre-filter and the carve-out. So the receiver leg is the only route to the engine's self-driving mode with fork-safety enforced nowhere — bypassing the control the code declares must never be bypassed (`tasks.py:73-75`: an auto-approval can satisfy required reviews with zero humans).
- **Found (fix is effective, unlike the URL-anchoring sibling):** `output.pr_url` is agent-reported via the task-run output API (`set_task_run_output`), not derived from a verified bot PR-creation response. Requiring the fetched PR to be bot-authored + repo-native would refuse a redirect to a human/fork attacker PR — closing the hole that URL validation alone cannot.
- **Impact:** A signal run that reports (via prompt-injected/mistaken agent output) a `pr_url` pointing at a fork or human-authored PR in one of the team's enabled Stamphog repos gets that PR privileged-reviewed and potentially approved, with no fork/bot/association gate anywhere — an errant GitHub approval that can satisfy required reviews. Reachable, though bounded to the team's own enabled repos and gated on the acting reviewer's toggle.
- **Priority:** Keeping must_fix. Note two overstatements in the suggestion that do NOT lower the core severity: re-verifying that `task_run_id` belongs to `team_id`/carries `signal_report_id` is largely redundant (the in-process review_hog caller already establishes these from the real TaskRun and Celery args aren't externally injectable), and the claim that webhook re-reviews 'treat stored pr_url alone as proof' is inaccurate (the carve-out already does bot+fork+facade-match). The genuinely missing controls are the bot-author and repo-native checks on the receiver leg's fetched PR.

### [❌ dismissed] should_fix · bug — products/stamphog/backend/tasks/tasks.py:1185-1201

**Receiver refires can create duplicate review workflows**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The deduplication uses `select_for_update()` only on matching `ReviewRun` rows. When no run exists for the current head, there is nothing to lock, so concurrent receiver tasks can both observe `existing is None`, create separate runs, and start duplicate Temporal/LLM reviews. This is especially plausible because every matching TaskRun output save refires this task.
- **Suggestion:** Serialize the check-and-create operation by locking the parent `PullRequest` row before querying `ReviewRun`, for example by reloading `pr_obj` through `select_for_update()` inside the transaction. Then perform the existing-head lookup, supersession, and creation while holding that lock. Alternatively, add a database-backed idempotency constraint specifically for inbox runs.
- **Validator:** - **Checked:** The receiver-leg transaction body in `process_inbox_pr_review` (tasks.py:1160-1220), `_upsert_pull_request` (tasks.py:319-363), `_start_review_workflow` (tasks.py:366-382), `_supersede_prior_runs` (tasks.py:415-430), the `PullRequest`/`ReviewRun` constraints (models.py:118-145,207-), and the webhook path's documented locking.
- **Found (the missed lock):** The dedup is not the `select_for_update()` alone. `_upsert_pull_request` runs first in the same `transaction.atomic`; its conditional `UPDATE ... WHERE payload_updated_at <= incoming` matches for same-head concurrent refires (identical GitHub snapshot) and takes the PR row's write lock held to commit, serializing the two transactions. On a first-ever review the `get_or_create` INSERT contends on `UniqueConstraint(team_id, repo_config, pr_number)` (models.py:120) instead. Either way T2 blocks until T1 commits, then its `existing` select sees T1's committed QUEUED run and no-ops.
- **Found (loser paths covered):** A transaction that does NOT get the lock only reaches that state via a stale/older snapshot (UPDATE matches 0 rows), and the stale-snapshot recheck (`pr_obj.payload_updated_at > incoming` → return) drops it before the create. This mirrors the webhook path's own comment: `_upsert_pull_request`'s conditional UPDATE takes the PR row lock, held to commit, serializing deliveries.
- **Found (only-gap unreachable):** The single unserialized branch is `incoming_updated_at is None` (early return before the conditional UPDATE, and the stale recheck is guarded on `incoming is not None`). GitHub PR payloads always include `updated_at`, so `get_pr` never yields None here.
- **Impact:** No duplicate Temporal/LLM reviews occur under realistic concurrency — the premise overlooks the PR-row / unique-index serialization that precedes the `existing` check, so it does not meet the bar (already handled). The suggested `(pull_request, head_sha)` uniqueness would additionally break legitimate same-head re-reviews (a base retarget creates a new run without moving the head).

### [❌ dismissed] must_fix · best_practice — products/stamphog/backend/tasks/tasks.py:1185-1190

**Queued initial reviews ignore a later toggle opt-out**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The Celery task trusts the toggle decision made before it was queued and stamps `inbox_review` without resolving the acting reviewer again. If the reviewer disables inbox reviews while this task is delayed or retrying, the task can still launch a privileged review and post an approval after opt-out. The webhook re-review path already rechecks this preference, so the initial path has inconsistent toggle semantics.
- **Suggestion:** Before creating or resuming the run, resolve the current acting reviewer through `get_inbox_acting_reviewer_resolver()` using the verified signal/task provenance. Return without starting a workflow when nobody is currently opted in, and use the freshly resolved user ID in the stamped provenance.
- **Validator:** - **Checked:** The initial-leg dispatch chain (`review_hog/receivers.py` `handle_task_run_saved` → `_start_stamphog_review` → `queue_inbox_pr_review.delay`), the Celery task config and body (`process_inbox_pr_review`, tasks.py:1108-1245), the webhook leg's re-check (`_inbox_rereview_carve_out` → `get_inbox_acting_reviewer_resolver`, tasks.py:201-207), and the opt-out skip handling in `process_pull_request_event` (tasks.py:880-909).
- **Found (observation is accurate but window is tiny):** The dispatcher checks `settings.stamphog_review_inbox_prs` immediately before `.delay()`, and the task (`max_retries=3, default_retry_delay=5`; rate-limit retries `max(retry_after,60)`) runs within seconds-to-minutes. The initial leg indeed does not re-resolve the toggle; the flip-off must land inside that short queue/retry window to matter.
- **Found (no invariant violated):** Any verdict the initial leg posts is over code it actually reviewed on the team's OWN positively-linked self-driving draft PR — not 'an approval over unreviewed code' (the invariant the product guards). The toggle is explicitly a preference, not a safety gate: AGENTS.md states a mid-PR toggle-off 'stops new runs' but 'safety is never preference-gated.'
- **Found (safety residual already handled):** If the initial leg posts an APPROVE after opt-out, the next head-changing webhook delivery hits `carve_out.opted_out=True` and calls `_retract_stale_approvals_on_skip(..., _INBOX_OPT_OUT_DISMISS_MESSAGE)` (tasks.py:894-898), dismissing the standing approval. With no subsequent push, the approval simply stands on the user's own draft PR they requested a review of moments earlier.
- **Impact:** A rare, benign preference-timing race on the user's own linked self-driving PR, with the only safety-relevant residual retracted by the webhook skip path on any later head change — no gate bypass beyond what other findings cover, and no stated invariant broken. Severity is far below the claimed must_fix; below the keep bar (rare/low-impact + already-handled). The 'privileged review / approval after opt-out' framing overstates it by implying an arbitrary target when it is the legitimately-linked PR.
