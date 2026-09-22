# P1-chained — resolution dump · posthog/posthog#72074

- dumped: 2026-07-18T01:07:51+00:00
- report: `019f7262-cf93-7401-afc2-e5500ed97b57` · run_count 1 · published_head `a6b30a8ec0952e22a181c048c02a95aaf80c8cf6`
- verdicts (latest per thread): **12**

## Per-thread verdicts

| thread                  | outcome  | author            | bot | reply_posted | resolved | commit     | watermark  | reasoning (head)                                                                                                |
| ----------------------- | -------- | ----------------- | --- | ------------ | -------- | ---------- | ---------- | --------------------------------------------------------------------------------------------------------------- |
| `PRRT_kwDODg-Tdc6R7p2F` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607136502 | Verified against current code + design docs. Technical claim confirmed: the hard floors are prose-only (prompt  |
| `PRRT_kwDODg-Tdc6R7p2H` | fixed    | posthog-local-dev | y   | y            | y        | ee1c41264c | 3607116826 | Confirmed the finding against current head. `_format_issue_comment` (publish_review.py:208-286) — the body tha  |
| `PRRT_kwDODg-Tdc6R7p2K` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607121002 | Verified against the current tree. reply_to_thread (github_threads.py:212-233) posts via addPullRequestReviewT  |
| `PRRT_kwDODg-Tdc6R7p2M` | fixed    | posthog-local-dev | y   | y            | y        | 3df70e5f3d | 3607126937 | Verified against the current tree. The PipelineSection intro (CodeReviewScene.tsx:216) reads 'Every review run  |
| `PRRT_kwDODg-Tdc6R7p2N` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607146250 | Verified. render*thread (thread_resolution.py:31-46) renders '--- {login} [{kind}, {association}] at {created*  |
| `PRRT_kwDODg-Tdc6R7p2P` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607131312 | Verified against current code. Absence of a deterministic author gate is real: \_prepare_run (resolution.py:159 |
| `PRRT_kwDODg-Tdc6R7p2Q` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607159363 | Confirmed against current code. Only guard on commit_sha is the pydantic model_validator fixed_requires_commit  |
| `PRRT_kwDODg-Tdc6R7p2S` | fixed    | posthog-local-dev | y   | y            | y        | ab986a8655 | 3607179508 | Same root cause as the reply*to_thread thread (PRRT*...p2K), which I escalated as an idempotency design decisi  |
| `PRRT_kwDODg-Tdc6R7p2T` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607189091 | Confirmed the chain against current code. /resolve (trigger.py:236-255) calls start_resolution_workflow with u  |
| `PRRT_kwDODg-Tdc6R7p2U` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607196981 | Confirmed mechanism. \_installation_auth returns github.get_access_token() as a bare token + installation_id (a |
| `PRRT_kwDODg-Tdc6R7p2V` | fixed    | posthog-local-dev | y   | y            | y        | 0b7f5bbb37 | 3607202671 | Verified at workflow.py:671-672: the guard around the resolve-pr child dispatch caught `except Exception` and   |
| `PRRT_kwDODg-Tdc6R7p2Y` | escalate | posthog-local-dev | y   | y            | n        | —          | 3607213920 | Confirmed gap against current code + sandbox contract. start_sandbox_session self-ends and raises on BOTH a sa  |

## Tallies

- outcomes: {'escalate': 8, 'fixed': 4}
- replies delivered: 12/12 · resolves delivered: 4/12

## Artefact trail (task_run / commit / note, oldest first)

- `23:21:46` **commit** {"repository":"PostHog/posthog","branch":"posthog-code/review-hog-resolution-stage-design","commit_sha":"a6b30a8ec0952e22a181c048c02a95aaf80c8cf6","message":"feat(review_hog): resolution stage — triage and implement a PR
- `00:35:23` **commit** {"repository":"PostHog/posthog","branch":"posthog-code/review-hog-resolution-stage-design","commit_sha":"ee1c41264cddb1dab2d12909a300b10d28dbc988","message":"Resolution fix for review thread on products/review_hog/backen
- `00:40:38` **commit** {"repository":"PostHog/posthog","branch":"posthog-code/review-hog-resolution-stage-design","commit_sha":"3df70e5f3ded892c9031c90bbf77154f111b7bdf","message":"Resolution fix for review thread on products/review_hog/fronte
- `00:57:09` **commit** {"repository":"PostHog/posthog","branch":"posthog-code/review-hog-resolution-stage-design","commit_sha":"ab986a8655df587d43e6379d1516c562fb02cf08","message":"Resolution fix for review thread on products/review_hog/backen
- `01:03:56` **commit** {"repository":"PostHog/posthog","branch":"posthog-code/review-hog-resolution-stage-design","commit_sha":"0b7f5bbb37e4ed3a4ab7ad800a9dcbd887b5d3ff","message":"Resolution fix for review thread on products/review_hog/backen
- `01:07:20` **note** {"note":"Resolution run on PR #72074: 12 thread(s) triaged (escalate 8, fixed 4); 0 redelivered, 0 already settled, 0 failed turn(s).","author":"review_hog_resolution"}

## Live GitHub state + CI (pasted by hand)

Live `reviewThreads` at 01:10Z (id suffix · isResolved · last comment id — compare to the verdict table above):

| thread    | resolved | last_comment | matches DB?                           |
| --------- | -------- | ------------ | ------------------------------------- |
| …dc6R7F0U | True     | 3606891272   | probe thread (P0.5), outside this run |
| …dc6R7p2F | False    | 3607136502   | ✓ (escalate, watermark ✓)             |
| …dc6R7p2H | True     | 3607116826   | ✓ (fixed+resolved, watermark ✓)       |
| …dc6R7p2K | False    | 3607121002   | ✓                                     |
| …dc6R7p2M | True     | 3607126937   | ✓                                     |
| …dc6R7p2N | False    | 3607146250   | ✓                                     |
| …dc6R7p2P | False    | 3607131312   | ✓                                     |
| …dc6R7p2Q | False    | 3607159363   | ✓                                     |
| …dc6R7p2S | True     | 3607179508   | ✓                                     |
| …dc6R7p2T | False    | 3607189091   | ✓                                     |
| …dc6R7p2U | False    | 3607196981   | ✓                                     |
| …dc6R7p2V | True     | 3607202671   | ✓                                     |
| …dc6R7p2Y | False    | 3607213920   | ✓                                     |

**12/12 verdict rows match live GitHub exactly** (resolved state + watermark = the stage's own posted reply). Resolves = exactly the 4 FIXED bot threads; 8 ESCALATE threads left unresolved (etiquette gate).

Resolver commits (all four `verified: true`, author `posthog-local-dev[bot]`):

- `ee1c41264c` fix(review_hog): recognize ReviewHog's own review threads via a stamped marker
- `3df70e5f3d` fix(review_hog): correct pipeline diagram intro for the resolve phase
- `ab986a8655` chore(review_hog): correct resolution crash-safety docstrings
- `0b7f5bbb37` chore(review_hog): log the exception when resolution dispatch fails

CI on head `0b7f5bbb37` at 01:12Z: 188 check runs, **0 failures** (rest queued/skipped-by-path; final SC4 read at report time).

## Spend (local `$ai_generation`, window ≥ 23:21Z)

- **Total gateway cost: $85.93.** Review legs ≈ $73.77 (chunking 0.39 + selection 0.05 + dedup 0.22 + 24× issues-review ≈ 38.9 (sonnet-5) + 8× blind-spots ≈ 10.1 + 8× validation ≈ 25.1 (opus-4-8)); **resolution session: $12.16** (69 gens, opus-4-8, 12.2M in / 11.8M cache-read / 151k out).
- Wall-clock: review 23:21:43→00:28:14 ≈ **66.5 min**; resolution 00:28:19→01:07:20 ≈ **39 min** (12 turns, ~3.3 min/turn).
