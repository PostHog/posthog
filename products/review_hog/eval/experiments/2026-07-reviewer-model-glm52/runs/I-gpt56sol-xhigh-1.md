# Reviewer-quality run — `I-gpt56sol-xhigh-1`

- **Dumped:** 2026-07-31T00:25:21+00:00
- **Report id:** `019fb571-da39-79e9-bc84-87ae19e76b87` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `1341596e721880256a1afb79bbc881364d00e302` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 1935s (32.2 min)

## Config snapshot

- runtime / model / effort: `codex` / `gpt-5.6-sol` / `xhigh`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 12           | 14         | 11          | 2                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.

### Cache-aware spend (local `$ai_generation`, best-effort)

| model           | stage                       | gens    | fresh in      | cache write | cache read    | output      | >200K gens | true $    | gw $       |
| --------------- | --------------------------- | ------- | ------------- | ----------- | ------------- | ----------- | ---------- | --------- | ---------- |
| claude-opus-4-8 | validation                  | 67      | 71,576        | 444,673     | 5,943,244     | 126,672     | 1          | $9.28     | $9.28      |
| gpt-5.6-sol     | review                      | 80      | 4,069,684     | 0           | 0             | 19,916      | 0          | —         | $5.96      |
| gpt-5.6-sol     | blind-spot                  | 24      | 1,186,032     | 0           | 0             | 7,463       | 0          | —         | $1.94      |
| claude-sonnet-5 | dedup                       | 1       | 8,055         | 0           | 0             | 7,811       | 0          | $0.09     | $0.09      |
| claude-sonnet-5 | other:perspective_selection | 1       | 5,981         | 0           | 0             | 2,218       | 0          | $0.03     | $0.03      |
| **total**       |                             | **173** | **5,341,328** | **444,673** | **5,943,244** | **164,080** | **1**      | **$9.40** | **$17.31** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = +0.0%.
- `true $` total excludes unpriced model `gpt-5.6-sol` (104 gen(s), gw $7.91).
- naive method (all prompt tokens at input price): $35.59 — 3.8× the true cost; never gate on it.
- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $13.2225 over 173 gen(s) (true $6.1368, Δ +115.5%)
  - · of which cache read: $5.1042 over 153 gen(s) (true $2.9716, Δ +71.8%)
  - · of which cache write: $2.7792 over 67 gen(s) (true $2.7792, Δ +0.0%)
  - · of which fresh (derived): $5.3391 over 173 gen(s) (true $0.3860, Δ +1283.4%)
  - output: $4.0885 over 173 gen(s) (true $3.2671, Δ +25.1%)
- 1 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit      | step                | first gen | t1 cache read | t1 cache write | models          |
| --------- | ------------------- | --------- | ------------- | -------------- | --------------- |
| …08681cdd | issues-review-p2-c3 | 23:54:02  | 0             | 0              | gpt-5.6-sol     |
| …f605b158 | issues-review-p3-c2 | 23:54:02  | 0             | 0              | gpt-5.6-sol     |
| …6f511d2f | issues-review-p2-c2 | 23:54:03  | 0             | 0              | gpt-5.6-sol     |
| …04bb9960 | issues-review-p3-c1 | 23:54:03  | 0             | 0              | gpt-5.6-sol     |
| …2c659630 | issues-review-p2-c1 | 23:54:04  | 0             | 0              | gpt-5.6-sol     |
| …f1a1450d | issues-review-p1-c3 | 23:54:04  | 0             | 0              | gpt-5.6-sol     |
| …04b028b4 | issues-review-p1-c1 | 23:54:06  | 0             | 0              | gpt-5.6-sol     |
| …edbd202e | issues-review-p1-c2 | 23:54:06  | 0             | 0              | gpt-5.6-sol     |
| …8e6bf4ae | issues-review-p1-c3 | 23:57:03  | 0             | 0              | gpt-5.6-sol     |
| …e3f9223e | issues-review-p2-c1 | 23:57:15  | 0             | 0              | gpt-5.6-sol     |
| …72b5b84d | issues-review-p3-c1 | 23:57:16  | 0             | 0              | gpt-5.6-sol     |
| …50538900 | blind-spots-c3      | 23:58:59  | 0             | 0              | gpt-5.6-sol     |
| …e78da583 | blind-spots-c2      | 23:59:02  | 0             | 0              | gpt-5.6-sol     |
| …3bee49fa | blind-spots-c1      | 23:59:03  | 0             | 0              | gpt-5.6-sol     |
| …d41f741d | blind-spots-c4      | 23:59:17  | 0             | 0              | gpt-5.6-sol     |
| …2512c7a9 | validation-c2       | 00:02:22  | 0             | 38,051         | claude-opus-4-8 |
| …bfe5600c | validation-c1       | 00:02:25  | 0             | 37,405         | claude-opus-4-8 |
| …0a641d2a | validation-c3       | 00:02:26  | 17,141        | 19,905         | claude-opus-4-8 |

- units with turn-1 cache_read > 0: **1/18** (report the distribution, not a median).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 24s      |
| review wave (perspectives)  | 5m 00s   |
| blind-spot sweep            | 2m 02s   |
| dedup (incl. combine/clean) | 1m 16s   |
| validation                  | 23m 28s  |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 7m 02s — the reviewer-model speed comparison number.
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
| 2    | 1     | review-hog-perspective-logic-correctness       | 3          |
| 2    | 2     | review-hog-perspective-logic-correctness       | 2          |
| 2    | 3     | review-hog-perspective-logic-correctness       | 1          |
| 3    | 1     | review-hog-perspective-performance-reliability | 1          |
| 3    | 2     | review-hog-perspective-performance-reliability | 2          |
| 1000 | 1     | ?                                              | 0          |
| 1000 | 2     | review-hog-blind-spots-general                 | 2          |
| 1000 | 3     | ?                                              | 0          |
| 1000 | 4     | ?                                              | 0          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] must_fix · security — tools/pr-approval-agent/review_local.py:321-321

**Security-sensitive flag accepts arbitrary truthy values**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `bool(context.get("self_driving_review"))` enables the bot-author and draft gate bypass for any truthy JSON value, including strings such as `"false"` or objects. This weakens the contract at the boundary controlling an approval-related security exception and can incorrectly label the provenance as verified.
- **Suggestion:** Require the exact JSON boolean value, for example `self_driving=context.get("self_driving_review") is True`, or validate the complete hosted context schema and fail closed when this field is not a boolean.
- **Validator:** - **Checked:** `review_local.py` module docstring and `_build_pr_data`/`run` to trace where `self_driving_review` and other boolean flags enter, and how the `context` dict is produced.
- **Found:** The docstring (`tools/pr-approval-agent/review_local.py:16-20`) states the `context` JSON is assembled by the server that holds the token — it is trusted, server-produced input, not attacker-controlled PR content. The PR author cannot set arbitrary top-level context keys like `self_driving_review`.
- **Found:** `bool(...)` coercion is the consistent house convention for every boolean read from this same context: `draft=bool(pr.get("draft"))` (line 195), `is_outdated=bool(thread.get("is_outdated"))`, `bool(comment.get("author_is_bot"))`. `draft` is itself one of the two security gates this feature relaxes and is read with the identical pattern — so the flagged line matches, not weakens, the established boundary convention.
- **Found:** Default-closed behavior is already correct: absent key → `None` → `bool(None) == False`; a proper JSON `false` → `bool(False) == False`. Divergence from `is True` requires the trusted server to serialize a non-boolean truthy value (e.g. string `"false"`), which a boolean flag serializer does not emit.
- **Impact:** The described bypass requires a producer-side malformation from trusted server code that cannot occur with normal JSON boolean serialization, and the input is not reachable by the PR author. This is speculative what-if / defensive-boundary paranoia rather than a reachable security or correctness defect, so it does not meet the bar to surface.

### [✅ VALID] must_fix · bug — products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py:7-9

**Migration introduces a conflicting 0019 leaf**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The app already contains `0019_reviewreport_author_login_and_more.py` and later migrations. Adding another migration numbered 0019 that also depends on 0018 creates two leaf nodes and causes Django's conflicting-migrations check to fail.
- **Suggestion:** Rebase this migration onto the current leaf, using the next available migration number and dependency, then update `products/review_hog/backend/migrations/max_migration.txt`. Run `python manage.py rebase_migration review_hog` or regenerate the migration and verify `makemigrations --check` reports no conflict.
- **Validator:** - **Checked:** the actual PR diff (`gh pr diff 75215`) for the migration and `max_migration.txt`, plus master's migration graph and every migration whose dependency is `0018_backfill_urgency_threshold_to_consider`.
- **Found:** the PR's `0019_reviewusersettings_stamphog_review_inbox_prs.py` declares `dependencies = [("review_hog", "0018_backfill_urgency_threshold_to_consider")]`, but master already has `0019_reviewreport_author_login_and_more.py` depending on the same `0018` parent, continuing through `0024_reviewreport_published_head_shas` (`products/review_hog/backend/migrations/0019_reviewreport_author_login_and_more.py:8`). On merge the graph has two siblings off `0018` and two leaf nodes (`0019_...stamphog` and `0024_...head_shas`).
- **Found:** the PR rewrites `max_migration.txt` from `0018...` to `0019_reviewusersettings_stamphog_review_inbox_prs`, colliding with master's `0024_reviewreport_published_head_shas` — the django-linear-migrations single-leaf gate this repo enforces.
- **Impact:** concrete blocker — `makemigrations --check` fails with "multiple leaf nodes", `max_migration.txt` conflicts, and CI's migration-conflict gate blocks the merge until the migration is renumbered onto the current `0024` leaf (`rebase_migration review_hog`). Meets the keep bar (contract/build break, directly introduced by the change) with a named trigger and consequence; `must_fix` is the right severity.

### [❌ dismissed] should_fix · bug — tools/pr-approval-agent/reviewer.py:568-568

**Self-driving reviews can still include bot familiarity signals**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The prompt concatenates both `familiarity_block` and `self_driving_block`. Hosted reviews call `_attach_familiarity` before the LLM review, so a T1 bot PR with any `author_pr_numbers` can receive a familiarity band and merged-history evidence. This contradicts the new provenance block's statement that machine-author familiarity and merged-PR history carry no signal, and may cause the reviewer to trust bot-wide history when judging an individual generated change.
- **Suggestion:** Suppress familiarity for self-driving runs before composing the prompt. For example, render `familiarity_block = ""` when `cl.get("self_driving")` is true, and also skip `_attach_familiarity` for these runs so telemetry and prompt state cannot imply author familiarity.
- **Validator:** - **Checked:** How `_attach_familiarity` gates the familiarity signal and how the server assembles `author_pr_numbers` vs `self_driving_review`, using the actual PR diff (`products/stamphog/backend/temporal/activities.py`, `tools/pr-approval-agent/review_local.py`, new integration test).
- **Found:** In `fetch_review_context` the PR adds `is_inbox_review = bool((run.output or {}).get("inbox_review"))` and sets `author_pr_numbers = client.get_author_merged_pr_numbers(repo, author) if author and not is_inbox_review else []` — for inbox/self-driving runs `author_pr_numbers` is hard-coded to `[]`, with a comment that the machine user's merged-PR familiarity is deliberately left absent so it isn't read as human trust context.
- **Found:** `self_driving_review=bool(output.get("inbox_review"))` keys off the same `run.output["inbox_review"]` provenance as `is_inbox_review`, so `self_driving` True ⇒ `author_pr_numbers == []` always; the two cannot diverge.
- **Found:** `_attach_familiarity` returns early on `raw_prs = context.get("author_pr_numbers"); if not raw_prs: return` (`review_local.py:301-303`), so empty `author_pr_numbers` leaves `familiarity` None, `_format_familiarity` returns `""`, and no familiarity block is concatenated — the contradiction the finding describes never renders.
- **Found:** The new `test_inbox_review_approves_a_selfdriving_draft_pr_end_to_end` asserts both `context["self_driving_review"] is True` and `context["author_pr_numbers"] == []`, commenting "the machine user's merged-PR history must not feed familiarity" — the invariant is pinned.
- **Impact:** The finding's trigger ("a T1 bot PR with any `author_pr_numbers`") is unreachable; the PR already suppresses `author_pr_numbers` for self-driving runs at the server layer, with a test. Already-handled / wrong-premise, so it does not meet the bar.

### [❌ dismissed] must_fix · security — products/stamphog/backend/tasks/tasks.py:1110-1155,1209-1232

**Initial inbox path can mark an unrelated PR as self-driving**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** This task trusts the caller-provided PR URL and provenance, then fetches any open PR in a configured repository and stamps `inbox_review`. It does not verify that `task_run_id` identifies a team-scoped signals implementation run, that its stored PR URL matches this PR, or that the fetched PR is bot-authored and repo-native. Because TaskRun output is produced by an agent, a forged or mistaken URL can make an unrelated human or fork PR enter the privileged self-driving engine path, bypassing the normal bot/draft safeguards and potentially receiving an automated approval.
- **Suggestion:** Before creating the run, resolve `task_run_id` through a team-scoped tasks facade and verify its signal report, repository, and recorded PR URL against the supplied provenance. Also require the fetched PR to satisfy the same bot-author and repo-native-head checks used by `_inbox_rereview_carve_out`. Derive `signal_report_id` and other provenance from the verified run rather than trusting Celery arguments; otherwise return without stamping `inbox_review`.
- **Validator:** - **Checked:** The caller of `process_inbox_pr_review` — `handle_task_run_saved` in `products/review_hog/backend/receivers.py:72-139` — plus how `output.pr_url` is written (`products/tasks/backend/webhooks.py:179-231`), the `find_task_run` matcher (`webhooks.py:30-79`), the webhook carve-out `_inbox_rereview_carve_out`, and the team-scoping inside the new task.

- **Found:** The initial-path trigger is a trusted internal `post_save` on a real team-scoped `TaskRun`, not an untrusted external event. The receiver already establishes the self-driving shape before dispatch: `task.signal_report_id is not None` (`receivers.py:98`), `not task.internal` (`:104`), and it passes the run's _own_ identifiers — `task_run_id=str(instance.id)` (`:137`), `signal_report_id=str(task.signal_report_id)` (`:136`), `pr_url=output.get("pr_url")` (`:93`). `_inbox_rereview_carve_out` does rigorous positive-ID because _its_ trigger is an arbitrary GitHub webhook (attacker can push any fork/human PR); that threat model does not transfer to the receiver leg.

- **Found:** In `process_inbox_pr_review`, `task_run_id`/`signal_report_id`/`acting_user_id` are only stamped as opaque provenance into `output={"inbox_review": {...}}` — they drive no cross-tenant fetch. Tenant isolation is enforced independently via `StamphogRepoConfig.objects.for_team(team_id)` (enabled + connected) and `ReviewRun.objects.for_team(team_id)`, so a wrong provenance id can only mislabel attribution, not cross a boundary.

- **Found:** `output.pr_url` is not free-form LLM output. It is set by the agent server observing the bot open its own PR (bot-authored, repo-native by construction) or by the fork-safe backstop `_record_run_pr_url`, which records only when `is_internal_branch` (`webhooks.py:179-186`) — the same fork guard the carve-out mirrors. The 'forged/fork PR URL enters the self-driving path' premise is thus not reachable; the target is constrained to the run's own repo-native bot PR inside the team's own connected+enabled repo.

- **Impact:** The requested re-verifications (re-resolve via `find_signal_implementation_run`, re-verify `pr_url` match, re-check bot-author/repo-native on the fetched PR) are belt-and-braces re-checks of invariants the trusted caller and the fork-safe `output.pr_url` write paths already establish — the 'already handled / defensive-coding paranoia' drop categories. 'Verify stored PR URL matches this PR' is also circular: the passed `pr_url` _is_ the stored `output.pr_url`. No concrete reachable trigger→consequence survives, so it does not meet the keep bar.

### [❌ dismissed] should_fix · security — products/tasks/backend/facade/api.py:484-506

**Team scoping is applied only after a cross-tenant TaskRun query**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** `find_signal_implementation_run` calls the unscoped `find_task_run` first and only checks `run.team_id` after an object has been selected. Besides crossing the tenant boundary unnecessarily, a matching run from another team can win the underlying `.first()` lookup and hide a valid run in the requested team. The facade therefore does not enforce team scoping at the query boundary as its contract claims.
- **Suggestion:** Add `team_id` as an explicit argument to `find_task_run` or implement the lookup here with `TaskRun.objects.filter(team_id=team_id, ...)`, applying the tenant predicate to every PR URL and branch lookup before ordering or selecting a row.
- **Validator:** - **Checked:** The full body of `find_signal_implementation_run` (from the PR diff), the `find_task_run` it delegates to (`products/tasks/backend/webhooks.py:30-79`), the sole caller `_inbox_rereview_carve_out`, and the function's own docstring/contract.

- **Found (no tenant leak):** After `run = find_task_run(...)` the code does `if run is None or run.team_id != team_id: return None`, and the `SignalImplementationRunDTO` is only constructed on the surviving same-team run. A cross-team match is discarded before any field is read — nothing from another tenant's run reaches the caller. The security/IDOR framing does not hold: the boundary IS enforced, just as a post-filter rather than a query predicate.

- **Found (docstring accurate):** The contract states 'a run belonging to any other team returns None … no caller can accidentally bind a PR to another tenant's run' — exactly the observed behavior. The reviewer's stronger paraphrase ('enforce team scoping at the query boundary') is not what the docstring claims.

- **Found (primary leg not shadowable):** `find_task_run`'s pr_url leg filters `output__pr_url=pr_url` AND `task__repository__iexact=repository` (`webhooks.py:42-44`), and the caller always supplies `pr_url=pr.get('html_url')` (always present on a `pull_request` webhook). A PR URL globally identifies one PR, recorded in `output.pr_url` only by the single team's run that produced it, so two teams cannot both match the same `output__pr_url` — the pr_url leg cannot be shadowed by another tenant. The branch leg (`filter(branch=..., task__repository__iexact=...)`), the only place a cross-team branch collision could win `.first()`, is reached solely when the pr_url leg finds nothing, and only if two teams share the same repo and a colliding head branch.

- **Impact:** The claimed 'hide a valid same-team run → None' requires that contrived multi-tenant shared-repo colliding-branch fallback case, and even then it is fail-safe: the carve-out returns None, the caller falls to the normal skip path which retracts any stale approval — a missed re-review, never a wrong or cross-tenant approval. Narrow, low-impact, with the security premise already closed by the existing post-filter — the defensive-paranoia / never-gonna-happen-edge drop categories. On the fence → drop.

### [❌ dismissed] must_fix · bug — products/review_hog/backend/receivers.py:111-125,144-154

**Only one assignee's opt-in is considered**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** The stated gate is that Stamphog runs when at least one assigned reviewer opts in, but `_resolve_assigned_reviewer` selects one canonical acting reviewer before the toggle is checked. If the task creator or first resolved reviewer is opted out while another assignee is opted in, both the initial dispatch and later webhook re-reviews are skipped incorrectly.
- **Suggestion:** Resolve all assigned organization members, then select an opted-in reviewer deterministically for the Stamphog path, preferring the assigned task creator when opted in and otherwise the first opted-in assignee. Use the same selection logic in `resolve_stamphog_acting_reviewer` so initial and webhook behavior remain consistent. Keep ReviewHog's existing single-reviewer selection semantics separate.
- **Validator:** - **Checked:** `_resolve_assigned_reviewer` selection logic and both toggle-gate call sites in `receivers.py`, the pre-existing `_resolve_acting_reviewer` it replaces (via the PR diff), the function docstring, and the webhook resolver `resolve_stamphog_acting_reviewer`.
- **Found:** the single-acting-reviewer model is not new — the old `_resolve_acting_reviewer` already gated `review_inbox_prs` on the one `acting.id` (diff line 135, removed), and the new code keeps that exact behavior, adding `stamphog_review_inbox_prs` as a parallel check on the same reviewer (`settings = ReviewUserSettings.load(...); if settings.review_inbox_prs ... if ... settings.stamphog_review_inbox_prs`, diff lines 62–74). `resolve_stamphog_acting_reviewer` reuses `_resolve_assigned_reviewer` identically (diff lines 102–107).
- **Found:** the docstring documents the single canonical reviewer as a deliberate choice — `acting = created_by when among resolved, else resolved[0]` — citing "maintainer decisions, 2026-07-02/03," and ties it to using that reviewer's ReviewHog options (perspectives / blind-spots / validator / urgency threshold) to drive the review; the PR's test comment reinforces it: "the two toggles on the one acting reviewer gate their reviews independently."
- **Impact (why it doesn't meet the bar):** the claimed bug rests on the PR description's simplified wording ("at least one of the assigned users"), which contradicts the actual, documented, intentional design that the sibling `review_inbox_prs` toggle has always followed. There is no regression and no divergence from established behavior. The reviewer's fix (scan all assignees for the toggle while keeping single-reviewer option semantics) is a design change that would split the two toggles' semantics and add complexity — overengineering, not a correctness fix. Premise is mistaken, so drop (precision over recall).

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:114-138

**A ReviewHog callback failure can prevent the independent Stamphog dispatch**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The ReviewHog callback is registered before the Stamphog callback, and both use Django's default `robust=False`. If `_start_review` raises before its internal `try` block, such as while importing its deferred Temporal modules, Django stops executing later commit callbacks. The Stamphog review is then never queued, despite its toggle being independent, and the exception can surface after the database transaction has committed.
- **Suggestion:** Register these fire-and-forget callbacks with `transaction.on_commit(..., robust=True)` and move each deferred import inside its protected `try` block. This keeps either integration's import or dispatch failure from blocking the other callback or escaping into the request/save path.
- **Validator:** - **Checked:** the two `transaction.on_commit` registrations (diff lines 64–74), the full body of `_start_review` (receivers.py:164-200) and `_start_stamphog_review` (diff lines 140-164) to locate what can raise outside their `try` blocks, and Django's `robust=False` on_commit semantics.
- **Found:** in `_start_review`, only the deferred imports at receivers.py:181-182 sit outside the `try`; the `target_kwargs` build and the `start_review_pr_workflow` call are inside `try/except Exception` (lines 188-200), which logs and swallows. `_start_stamphog_review` mirrors this (deferred import outside, `queue_inbox_pr_review` call inside `try`). So the realistic failure — Temporal/broker unavailable — is already caught in both and never propagates to halt the sibling callback.
- **Found:** the reviewer's Django claim is accurate (a raising `robust=False` hook stops later hooks), but the only trigger is the deferred import of `products.review_hog.backend.temporal.client`/`.types` actually raising. Those modules are imported on the first inbox review and cached in `sys.modules` thereafter, so the import is a no-op lookup; a real ImportError is a systemic deploy misconfiguration that breaks every ReviewHog inbox review anyway, not a transient per-save condition.
- **Impact (why it doesn't meet the bar):** the scenario where the ReviewHog callback's exception skips the stamphog dispatch requires a practically-unreachable import failure — the realistic runtime failure (workflow start error) is already handled inside the `try`. The 'exception surfaces post-commit' aspect is pre-existing to `_start_review` and gated on the same unreachable trigger. This is a never-gonna-happen edge / defensive-robustness nicety, not a failure mode that will occur; precision over recall → drop.

### [❌ dismissed] must_fix · bug — products/stamphog/backend/tasks/tasks.py:1200-1228

**Head-keyed deduplication does not serialize concurrent task deliveries**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** `select_for_update()` only locks an existing `ReviewRun`. When two receiver-triggered tasks process the same PR head concurrently and no run exists yet, both queries return `None`, both create a row, and both start separate Temporal workflows. `ReviewRun` has no uniqueness constraint on `(pull_request, head_sha)`, so duplicate reviews and conflicting GitHub output remain possible despite the stated deduplication guarantee.
- **Suggestion:** Enforce deduplication at the database boundary. Add an appropriate unique constraint or idempotency key for inbox runs and create with conflict handling, or lock the parent `PullRequest` row before checking for an existing run so concurrent executions serialize. Handle the resulting `IntegrityError` by loading and resuming the winning run.
- **Validator:** - **Checked:** The full `process_inbox_pr_review` atomic block (PR diff), `_upsert_pull_request` (`products/stamphog/backend/tasks/tasks.py:204-248`), the model constraints on `PullRequest` and `ReviewRun` (`products/stamphog/backend/models.py:78-173`), and the webhook path's documented serialization comment (`tasks.py:894-898`).

- **Found (premises right, conclusion wrong):** `ReviewRun` indeed has no `(pull_request, head_sha)` unique constraint (`models.py:140-173`; `delivery_id` is unique-but-nullable and inbox runs pass `delivery_id=None`), and `select_for_update()` over an absent row locks nothing. But the predicted double-create cannot occur, because both concurrent fires must first execute `pr_obj = _upsert_pull_request(repo_config, pr)` — the first statement in the same `transaction.atomic(using=run_write_db)` block, on the same PR — before reaching the `ReviewRun` check.

- **Found (serialization point):** `_upsert_pull_request` calls `PullRequest.objects.for_team(team_id).get_or_create(repo_config=..., pr_number=...)` against unique constraint `unique_stamphog_pull_request` on `(team_id, repo_config, pr_number)` (`models.py:120-121`). No PR row yet: the loser's duplicate INSERT blocks until the winner commits, then catches IntegrityError and re-fetches. PR row exists: the conditional refresh `.update(...)` (`tasks.py:234-239`) takes the PR row lock held to commit — the exact mechanism the webhook path documents at `tasks.py:894-898`. Either way the two fires serialize on the PullRequest row.

- **Found (loser sees winner's run):** After the winner commits its `ReviewRun`, the loser unblocks and under READ COMMITTED its `select_for_update().filter(pull_request=pr_obj, head_sha=head_sha)` sees the committed run and returns via `existing is not None` — no second create, no second workflow. Both fires carry the same `head_sha` (same fetched PR), so the filter matches.

- **Impact:** The stated failure (two rows, two workflows, conflicting GitHub output) is unreachable; dedup holds via PR-row serialization. The only unserialized crack — existing PR row AND `incoming_updated_at is None` skipping the UPDATE lock (`tasks.py:231-233`) — cannot happen here because the PR is fetched fresh from GitHub, whose payloads always carry a parseable `updated_at`. Does not meet the bar.

### [❌ dismissed] should_fix · performance — products/tasks/backend/facade/api.py:505-508

**Unmatched bot PRs can trigger an unindexed TaskRun branch scan**  
_perspective: review-hog-perspective-performance-reliability · directly-related: True_

- **Problem:** The new webhook carve-out calls `find_task_run` for bot-authored PRs. If its indexed `output.pr_url` lookup misses, that helper falls back to filtering `TaskRun.branch` plus the related task repository and ordering by creation time. `TaskRun.branch` has no supporting index, so unrelated bot PR deliveries can cause an increasingly expensive scan of the TaskRun table on every synchronize or reopen event.
- **Suggestion:** Avoid the branch fallback when the authoritative PR URL was supplied, or add a query/index strategy that supports the fallback, such as an index beginning with `branch` and covering the ordering while retaining the repository join filter. Validate the chosen query with `EXPLAIN` against the expected table size.
- **Validator:** - **Checked:** `find_task_run`'s branch fallback (`products/tasks/backend/webhooks.py:62-79`), the `TaskRun`/`Task` index definitions (`products/tasks/backend/models.py:1537`, `1600-1630`; `183-185`, `266-272`), how the carve-out reaches it via `find_signal_implementation_run`, and the pre-existing caller `handle_pull_request_event` (`webhooks.py:130-217`).

- **Found (premise technically correct):** `TaskRun.branch` (`models.py:1537`) has no index and is absent from `Meta.indexes` (`1603-1630`); `Task.repository` (`183-185`) is unindexed too, and `__iexact` would defeat a btree anyway. The branch leg `filter(branch=..., task__repository__iexact=..., state__wizard_head_branch__isnull=True).first()` (default `-created_at` ordering) is scan-prone, and `find_signal_implementation_run` does fall into it when the indexed `output.pr_url` lookup misses.

- **Found (self-driving target never hits the scan):** The `output.pr_url` leg is index-backed (`task_run_output_pr_url_idx`, `models.py:1609-1613`) and runs first. A real self-driving PR records `output.pr_url` when opened, so on every later synchronize the pr_url leg matches and short-circuits; the branch leg is reached only for bot PRs whose URL matches no run (dependabot/renovate etc.), which never match the branch leg either — wasted work, but only for non-target PRs.

- **Found (pre-existing, production-exercised query):** The identical branch leg is already invoked by the tasks webhook `handle_pull_request_event` → `find_task_run` (`webhooks.py:160`) on every `opened`/`closed` PR across all tasks-app repos as the `_record_run_pr_url` backstop when the agent-side detector hasn't recorded the URL yet. Its index profile is a long-standing accepted cost, not introduced by this PR; the carve-out adds a bounded subset (bot-authored + repo-native + stamphog-enabled + pr_url-miss).

- **Impact:** Runs async inside the `process_pull_request_event` Celery task, not on the webhook request path. Stamphog is gated behind a per-user toggle plus an enabled repo config (experimental), so current invocation volume is tiny and 'increasingly expensive scan at real scale' is speculative about future broad rollout of a query that already runs at comparable/higher volume elsewhere without being a known issue. Real but bounded, pre-existing, and only for non-target PRs — below the 'bites at real scale / new problem' bar. On the fence → drop.

### [✅ VALID] must_fix (validator→consider) · security — products/tasks/backend/facade/api.py:500-508

**Branch fallback can authorize a different PR**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** When the exact PR URL does not match, find_task_run falls back to repository and branch. That fallback can return an old or otherwise unrelated run, including one whose output already names a different PR. The webhook carve-out then treats the current bot-authored PR as self-driving and permits an automated approval. Reusing a branch or opening a second PR from it is enough to trigger the incorrect binding.
- **Suggestion:** For this authorization-sensitive facade, accept a branch match only when the selected run has no recorded pr_url, and reject it when output.pr_url differs from the supplied URL. Perform the team-scoped lookup directly and prefer active runs deterministically.
- **Validator:** - **Checked:** The non-wizard branch leg of `find_task_run` (`products/tasks/backend/webhooks.py:65-79`) vs the adjacent wizard leg (`:82-97`), how `find_signal_implementation_run` forwards both `pr_url` and `head_branch` to it, and the carve-out gates in `_inbox_rereview_carve_out` that guard what reaches this facade.

- **Found (gap is real):** The non-wizard branch leg `filter(branch=branch, task__repository__iexact=repository, state__wizard_head_branch__isnull=True).first()` (`webhooks.py:69-77`) applies no `output.pr_url` consistency check and no terminal-status exclusion, returning the newest branch-matching run (default `-created_at`) regardless of which PR its `output.pr_url` names. The sibling wizard leg DOES `.exclude(status__in=_TERMINAL_RUN_STATUSES)` precisely 'so a reopened branch can't fire events on a dead run' (`:82-84`) — the authors saw this hazard but the non-wizard leg lacks the guard. `find_signal_implementation_run` adds no pr_url-match check, so a branch-matched run whose recorded PR differs from the incoming one still yields a DTO and the carve-out authorizes the incoming PR as self-driving.

- **Found (reachability narrow, blast radius bounded):** The branch leg is only reached when the indexed `output.pr_url` leg misses; for a genuine self-driving PR the URL is recorded once opened, so normal-flow synchronizes match on pr_url and never reach it. Mis-binding needs an abnormal state — a second PR sharing a prior signals run's head branch (branch reuse after close, or a second base) — and the common re-run case binds to the newest branch-B run (often correct). The incoming PR is also provably bot-authored (`_is_bot_authored`) and repo-native (`head_repo == repo` fork check), in an enabled/synced/connected stamphog repo, with an opted-in SR reviewer required — so the mis-bound PR is always a bot, repo-native PR in the team's own opted-in repo, not an arbitrary human/fork PR.

- **Impact:** In that edge state a bot PR could get a self-driving review and automated approval attributed to an unrelated signal report's reviewers, bypassing the bot/draft gate — a genuine authorization-consistency gap in a facade whose documented job is to 'positively identify' the run, with a cheap fix (reject a branch match when the run's `output.pr_url` is set and differs). But abnormal-state reachability, newest-run-wins ordering fixing the common case, and the bounded bot/repo-native/own-repo blast radius put it well below `must_fix`.

- **Priority:** Lowered to `consider` — real and worth recording, but edge-case reachable with bounded blast radius, not urgent.

### [❌ dismissed] should_fix · best_practice — products/stamphog/backend/tasks/tasks.py:1107-1115,1182-1187

**Queued initial reviews ignore later opt-out**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** The initial Celery task trusts the acting_user_id resolved before dispatch and never rechecks the reviewer assignment or stamphog toggle. If the task waits in the queue, retries after a transient failure, or the reviewer disables the feature before execution, it still stamps inbox provenance and runs the review contrary to the current preference. The webhook re-review path performs this freshness check, but the initial path does not.
- **Suggestion:** Before creating the ReviewRun, resolve the acting reviewer again from the team-scoped signal/task provenance and return without reviewing when nobody currently qualifies. Keep the queued acting_user_id only as advisory attribution, or replace it with the freshly resolved ID.
- **Validator:** - **Checked:** The `process_inbox_pr_review` body (PR diff) for any reviewer/toggle re-resolution, how `acting_user_id` is used inside it, the dispatch site in `receivers.py` (`_start_stamphog_review` via `transaction.on_commit`), and how the design characterizes the toggle vs safety (`_inbox_rereview_carve_out` docstring).

- **Found (gap real but input fresh by construction):** `process_inbox_pr_review` re-checks nothing about opt-in — its only gate is `repo_config...enabled=True`, and `acting_user_id` flows straight into the `inbox_review` provenance dict with no gating role. But the task is dispatched via `transaction.on_commit(lambda: _start_stamphog_review(...))` (`receivers.py:131-139`) immediately after the receiver read `settings.stamphog_review_inbox_prs` (`:126`), so the trusted value was verified microseconds earlier; the race window is seconds (default retry delay 5s), not the open-ended gap the webhook path faces. The webhook path re-resolves through the resolver precisely because its trigger (an arbitrary later push, possibly days on) is temporally decoupled from any prior check — the asymmetry is justified, not an oversight.

- **Found (toggle is preference, not safety; harm self-corrects):** The design explicitly states 'safety is never preference-gated' (`_inbox_rereview_carve_out` docstring) — approval retraction is independent of the toggle. A stale toggle read causes at most one initial review of the team's own bot, repo-native, draft PR in an enabled repo. If the reviewer had truly opted out, the next head-changing event routes through the webhook carve-out's `opted_out=True` path and dismisses any standing approval via `_INBOX_OPT_OUT_DISMISS_MESSAGE`. And if multiple reviewers are opted in, one toggling off wouldn't change the resolved outcome.

- **Impact:** The failure needs a reviewer to flip the toggle off in the exact seconds-window between the agent autonomously opening the PR and the queued task running — an uncorrelated narrow race — and yields only a single preference-stale review whose approval self-corrects on the next push. Defensive re-checking of a value already fresh at dispatch, guarding a preference the design deliberately decouples from safety — below the keep bar (defensive-paranoia / never-gonna-happen edge). On the fence → drop.
