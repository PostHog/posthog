# Reviewer-quality run — `J-gpt56sol-seq-2`

- **Dumped:** 2026-07-31T09:11:34+00:00
- **Report id:** `019fb731-4834-71f4-8863-7010a1f5831d` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 2 · **status:** idle
- **Wall-clock:** 1141s (19.0 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 25           | 15         | 14          | 6                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read    | output     | >200K gens | true $    | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | ------------- | ---------- | ---------- | --------- | ---------- |
| gpt-5.6-sol     | review                      | 111     | 5,785,449     | 0           | 0             | 27,305     | 0          | —         | $8.28      |
| claude-opus-4-8 | validation                  | 53      | 51,442        | 315,205     | 5,217,388     | 48,074     | 0          | $6.04     | $6.04      |
| gpt-5.6-sol     | blind-spot                  | 26      | 1,350,608     | 0           | 0             | 5,591      | 0          | —         | $2.02      |
| claude-sonnet-5 | dedup                       | 1       | 14,291        | 0           | 0             | 377        | 0          | $0.03     | $0.03      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0             | 1,460      | 0          | $0.03     | $0.03      |
| **total**       |                             | **192** | **7,207,771** | **315,205** | **5,217,388** | **82,807** | **0**      | **$6.10** | **$16.39** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.0%.
- `true $` total excludes unpriced model `gpt-5.6-sol` (137 gen(s), gw $10.30).
- naive method (all prompt tokens at input price): $29.18 — 4.8× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $14.1851 over 192 gen(s) (true $4.8765, Δ +190.9%)
  - · of which cache read: $5.5389 over 169 gen(s) (true $2.6087, Δ +112.3%)
  - · of which cache write: $1.9700 over 53 gen(s) (true $1.9700, Δ +0.0%)
  - · of which fresh (derived): $6.6762 over 192 gen(s) (true $0.2978, Δ +2142.2%)
  - output: $2.2071 over 192 gen(s) (true $1.2202, Δ +80.9%)

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …62657b93 | issues-review-p3-c2 | 08:53:36  | 0             | 0              | gpt-5.6-sol     |
| …49fb5c58 | issues-review-p2-c3 | 08:53:36  | 0             | 0              | gpt-5.6-sol     |
| …db5406bd | issues-review-p2-c2 | 08:53:37  | 0             | 0              | gpt-5.6-sol     |
| …9fd40be8 | issues-review-p3-c3 | 08:53:37  | 0             | 0              | gpt-5.6-sol     |
| …7422e084 | issues-review-p1-c3 | 08:53:37  | 0             | 0              | gpt-5.6-sol     |
| …c4152fc3 | issues-review-p2-c1 | 08:53:39  | 0             | 0              | gpt-5.6-sol     |
| …7b946f61 | issues-review-p3-c1 | 08:53:39  | 0             | 0              | gpt-5.6-sol     |
| …65adefe6 | issues-review-p1-c1 | 08:53:40  | 0             | 0              | gpt-5.6-sol     |
| …d40b5d59 | issues-review-p1-c2 | 08:53:40  | 0             | 0              | gpt-5.6-sol     |
| …345b1852 | issues-review-p2-c1 | 08:56:54  | 0             | 0              | gpt-5.6-sol     |
| …5555b4a4 | issues-review-p1-c1 | 08:56:55  | 0             | 0              | gpt-5.6-sol     |
| …13c1f822 | issues-review-p2-c2 | 08:56:56  | 0             | 0              | gpt-5.6-sol     |
| …b17c8c17 | issues-review-p3-c1 | 08:57:00  | 0             | 0              | gpt-5.6-sol     |
| …453088b2 | issues-review-p1-c2 | 08:57:01  | 0             | 0              | gpt-5.6-sol     |
| …6390c87f | issues-review-p3-c2 | 08:57:19  | 0             | 0              | gpt-5.6-sol     |
| …00bcfb73 | blind-spots-c2      | 08:59:30  | 0             | 0              | gpt-5.6-sol     |
| …866bef79 | blind-spots-c3      | 08:59:33  | 0             | 0              | gpt-5.6-sol     |
| …4cfe8832 | blind-spots-c1      | 08:59:33  | 0             | 0              | gpt-5.6-sol     |
| …8241b260 | blind-spots-c4      | 08:59:35  | 0             | 0              | gpt-5.6-sol     |
| …6cffbabd | validation-c2       | 09:01:39  | 0             | 37,914         | claude-opus-4-8 |
| …ce94e76c | validation-c1       | 09:01:41  | 17,141        | 20,264         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **1/21** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 50m 32s  |
| chunking                    | 0s       |
| perspective selection       | 19s      |
| review wave (perspectives)  | 6m 16s   |
| blind-spot sweep            | 2m 06s   |
| dedup (incl. combine/clean) | —        |
| validation                  | 62m 08s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 8m 23s — the reviewer-model speed comparison number.
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
| 1    | 1     | ?                                              | 0          |
| 1    | 2     | review-hog-perspective-contracts-security      | 1          |
| 1    | 2     | review-hog-perspective-contracts-security      | 2          |
| 1    | 3     | ?                                              | 0          |
| 1    | 3     | review-hog-perspective-contracts-security      | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 1     | review-hog-perspective-logic-correctness       | 1          |
| 2    | 2     | ?                                              | 0          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | ?                                              | 0          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 2          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 1          |
| 3    | 3     | ?                                              | 0          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 1          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |
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

### [✅ VALID] must_fix · security — products/stamphog/backend/tasks/tasks.py:124-127,161-171

**Carve-out trusts any bot identity as the self-driving author**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The privileged webhook path only verifies that the PR author is some GitHub bot. A different installed bot with repository write access can open a repo-native PR from a branch associated with a signal implementation run and inherit the bypass of draft, review-mode, and author-permission gates. The task lookup proves a related run exists, but it does not prove this bot created the PR.
- **Suggestion:** Require the expected PostHog Code GitHub App bot login and confirm the matched run used bot authorship before granting provenance. Add those identity facts to SignalImplementationRunDTO if necessary, and fail closed when the expected bot identity cannot be established.
- **Validator:** - **Checked:** `_inbox_rereview_carve_out` (products/stamphog/backend/tasks/tasks.py:144-215), its author gate `_is_bot_authored` (tasks.py:124-127), the run lookup `find_signal_implementation_run` (products/tasks/backend/facade/api.py:484-516) and its `find_task_run` matcher (products/tasks/backend/webhooks.py:30-99), plus the product's own bot-identity model in logic/github_client.py and products/stamphog/CLAUDE.md.
- **Found:** The carve-out grants a review + approval bypass on an 'any Bot' floor (tasks.py:169 calls `_is_bot_authored`, which returns True for `user.type == 'Bot'` OR `'[bot]' in login`). Its own comment at tasks.py:170-171 asserts the stronger invariant it does not enforce ('authorship is forced to the team's GitHub App machine user').
- **Found:** The run match is not authorship proof. `find_task_run`'s branch leg (webhooks.py:69-77) matches on `branch == pr.head.ref` + repository and, unlike the wizard leg, does NOT exclude terminal runs — so any past or present non-wizard signal-implementation run's branch name in that repo satisfies it. Fork-safety (tasks.py:176-178) only enforces repo-native head, not author identity.
- **Found:** The same product treats 'any Bot' trust as unacceptable for approval-adjacent decisions: `_is_own_bot_actor(..., allow_any_bot=False)` requires the exact `<slug>[bot]` (github_client.py:53-69), and CLAUDE.md:32-33 states a fuzzy 'any Bot' match 'must never dismiss or adopt another bot's review.' The carve-out is precisely such an approval-adjacent decision using the forbidden fuzzy floor.
- **Impact:** An attacker-controlled bot with repository write access can open a repo-native PR whose head branch reuses a signal-run branch name, pass the 'any Bot' floor and the branch-leg run match, and inherit the draft/bot/review-mode/write-permission bypass — causing StampHog to review and potentially post a standing GitHub approval on a PR that is not genuinely a PostHog Code self-driving run. This is a real trust-boundary gap consistent with the product's documented invariant, and the requested fix (require the expected `<slug>[bot]` login, confirm bot authorship on the matched run, fail closed when identity is unestablished) matches the existing `allow_any_bot=False` pattern.

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:7-9

**Rebase this migration onto the current ReviewHog migration leaf**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** This adds a second `0019` migration depending on `0018`, while the app already has an existing migration chain from `0019_reviewreport_author_login_and_more` through `0024_reviewreport_published_head_shas`. Django will detect two conflicting leaf migrations and refuse to migrate.
- **Suggestion:** Run `python manage.py rebase_migration review_hog` so this becomes the next migration after `0024_reviewreport_published_head_shas` (currently `0025`), and update `max_migration.txt` accordingly.
- **Validator:** - **Checked:** the full `products/review_hog/backend/migrations/` chain on master, the fork point's `dependencies`, `max_migration.txt`, and whether django_linear_migrations is active.
- **Found:** master already has `0019_reviewreport_author_login_and_more` → ... → `0024_reviewreport_published_head_shas`, and `0019_reviewreport_author_login_and_more.py:8` depends on `0018_backfill_urgency_threshold_to_consider`. The PR's new `0019_reviewusersettings_stamphog_review_inbox_prs` also depends on `0018`, so `0018` now has two children and the graph has two leaves (`0024` and the new `0019`). `max_migration.txt` currently pins the single leaf `0024_reviewreport_published_head_shas`.
- **Found:** `django_linear_migrations` is installed (`posthog/settings/web.py:207`), so besides Django's own "multiple leaf nodes" error on migrate/makemigrations, the linear-migrations consistency check (single leaf must match `max_migration.txt`) fails in CI.
- **Impact:** Concrete trigger — merging this branch onto current master; concrete consequence — `manage.py migrate`/`makemigrations --check` errors with conflicting leaf nodes and CI blocks, so the migration never applies. The suggested `rebase_migration review_hog` (renumber to `0025` after `0024` and update `max_migration.txt`) is the correct remedy. Matches the PR's `dirty` mergeable state.

### [❌ dismissed] must_fix · bug — products/review_hog/backend/receivers.py:114-114,151-155

**Pin toggle gates to the writer database**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** Both the initial dispatch and webhook re-review gate call `ReviewUserSettings.load()` through the default read route. A recently changed toggle can therefore be read from a lagging replica. Most critically, a webhook arriving immediately after opt-out may observe the old `true` value and launch a review that can restore an approval the user intended to disable. Stamphog's existing `enabled` gates explicitly pin reads to `router.db_for_write(...)` to avoid this failure mode.
- **Suggestion:** Load `ReviewUserSettings` from the writer for these decision gates, for example by adding a writer-pinned settings loader using `.using(router.db_for_write(ReviewUserSettings))`, and use it in both the TaskRun receiver and `resolve_stamphog_acting_reviewer`.
- **Validator:** - **Checked:** the two active DB routers (`posthog/dbrouter.py`, `posthog/product_db_router.py`), the product-DB registry `products/db_routing.yaml`, the replica opt-in setting, and `ReviewUserSettings.load()` itself.
- **Found:** `ReviewUserSettings` is in the `review_hog` app (`products/review_hog/backend/apps.py:6`), which is NOT listed in `products/db_routing.yaml` (only `stamphog`, `visual_review`, `warehouse_sources_queue` are). So `ProductDBRouter.db_for_read`/`db_for_write` return `None` for it — no reader/writer split.
- **Found:** `ReplicaRouter.db_for_read` (`posthog/dbrouter.py:22-31`) sends reads to `"replica"` only when the model name is in `READ_REPLICA_OPT_IN`, else `"default"`. `READ_REPLICA_OPT_IN` is env-driven and empty by default (`posthog/settings/data_stores.py:271-272`), and nothing opts `ReviewUserSettings` in. `load()` (`products/review_hog/backend/models.py:363-367`) issues a plain `.for_team(...).filter(...).first()` with no `.using()`, so it already reads from `default` (the writer/primary) — a strongly-consistent read.
- **Found:** Stamphog's `db_for_write` pins exist because Stamphog IS a registered product DB whose `db_for_read` returns `stamphog_db_reader`, a genuine lagging replica (`posthog/product_db_router.py:27-35`, and its own code comments warn about a "lagged reader"). That rationale is specific to product-DB models and does not transfer to a main-DB model.
- **Impact:** The finding's premise (stale read from a lagging replica → webhook restoring an approval after opt-out) cannot occur here — the read is already against the primary. The suggested `.using(router.db_for_write(ReviewUserSettings))` resolves to `"default"`, exactly the current read target, so it is a no-op that only adds misleading ceremony. Wrong/unreproducible: a sibling-product convention misapplied to a differently-routed model.

### [✅ VALID] should_fix · performance — products/stamphog/backend/tasks/tasks.py:1201-1207

**Failed reviews can be relaunched repeatedly for the same commit**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The deduplication explicitly excludes FAILED runs. Because the TaskRun receiver deliberately fires again whenever output is saved, every subsequent save can create another ReviewRun for the same unchanged head after a deterministic failure. A permanently failing repository or reviewer configuration can therefore repeatedly consume Temporal, sandbox, GitHub, and LLM capacity without any new code to review.
- **Suggestion:** Treat a FAILED run for the same head as handled, or add a bounded retry policy keyed by pull request and head SHA with an attempt limit and cooldown. Require a new head or an explicit manual retry to launch further reviews after that budget is exhausted.
- **Validator:** - **Checked:** the dedup at `process_inbox_pr_review` (products/stamphog/backend/tasks/tasks.py:1202-1210), what re-fires it (review_hog/backend/receivers.py `handle_task_run_saved` + `_start_stamphog_review` → facade `queue_inbox_pr_review`), the stamphog workflow-id/reuse policy (products/stamphog/backend/temporal/client.py:43-48), and the webhook path's create/dedup (tasks.py:1054-1073) for comparison.
- **Found:** The dedup query excludes both SUPERSEDED and FAILED (tasks.py:1207 `.exclude(status__in=(ReviewRunStatus.SUPERSEDED, ReviewRunStatus.FAILED))`), so once a review for a given `head_sha` terminates FAILED, `existing` is None and a new QUEUED ReviewRun is created; there is no attempt cap or per-(PR,head) cooldown anywhere.
- **Found:** The trigger is not head-change-gated. `handle_task_run_saved` fires on every TaskRun `output` save carrying `pr_url`, gated only by the _TaskRun's_ own status (receivers.py `if instance.status in (FAILED, CANCELLED): return`) — not the ReviewRun's. The module docstring states the implementation run deliberately stays `in_progress` and is babysat, so `output` is saved repeatedly for an unchanged PR head.
- **Found:** Nothing collapses the re-launch at the Temporal layer: the workflow id is `f"stamphog-review-{review_run_id}"` (client.py:43), keyed per ReviewRun, so each new row starts a _fresh_ full sandbox+LLM+GitHub review. This is the ReviewHog leg's deterministic-workflow-id + USE_EXISTING collapse (receivers.py docstring) that the stamphog leg lacks specifically after a FAILED run.
- **Found (asymmetry):** The webhook path (tasks.py:1054-1073) is naturally bounded — it keys on GitHub `delivery_id` idempotency, and GitHub does not redeliver an unchanged head — so it never loops on the same commit. The inbox receiver leg is uniquely exposed because its trigger repeats for an unchanged head.
- **Impact:** A deterministically failing review (e.g. a repo whose gateway-credential minting or egress config always fails, or a PR that reliably crashes the engine — realistic `mark_review_failed` causes) re-launches a full sandbox+LLM+GitHub+Temporal run on every subsequent TaskRun output save with no new code to review, and records repeated FAILED runs. Transient failures self-heal (a success re-arms the dedup), so the exposure is the deterministic-failure class — a real resource/reliability defect with a concrete, cheap fix (treat same-head FAILED as handled, or cap/cooldown by PR+head). `should_fix` is appropriate given the deterministic-failure precondition.
