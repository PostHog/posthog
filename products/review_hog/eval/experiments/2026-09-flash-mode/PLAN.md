# PLAN — Flash mode (GLM 5.3 Flash in the reviewer and validator seats)

**Question:** is a cheap "Flash" review, the existing pipeline with `zai-org/glm-5.3-flash` @ `high` in both
sandbox seats, worth running on every PR the way Greptile and CodeRabbit are, with the full Sol/Opus review kept
for the PRs that matter? The 2026-08 experiment (`../2026-08-model-glm53-flash/`) measured GLM against the prod
pins on one frozen PR; this one ships Flash as a run mode and measures it on ~100 real PRs by hand.

## Luna reasoning-effort follow-up (2026-09-17)

Completed `luna-medium-1` / `luna-medium-2` (MA / MB) and `luna-xhigh-1` / `luna-xhigh-2` (XA / XB), with all 66 findings judged by three independent verifiers and compared against the six baseline runs.
The reviewed head remains `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82`, with the same four pinned chunks, empty PR comments, concurrency four, Flash seats, and database-only output.

- Preflight passed: a Sonnet one-shot reached the gateway and Kafka with cost `$0.000578`; a two-turn Luna medium sandbox checked out the frozen branch, retained its response across the follow-up, and recorded three gateway calls costing `$0.0061616` with actual effort `medium`.
- The first smoke attempt exposed an orphaned Temporal worker after hot reload. Its replacement could not bind port 8001, leaving the workflow stalled after image creation. Restarting the configured service cleared it. Smoke runs are excluded from measured costs and times, and their sandboxes were cleaned up.
- Runtime checkout: `c0e58940541edeb01ec55e410338750a6368308c`. ReviewHog code and experiment inputs match pinned `4cf3e5471286cbac0a0960b9966aa0c55e92b7f5`; shared runtime changes include Temporal executor sizing. The follow-up also runs on another machine, so timing comparisons with the earlier arms have an additional environment caveat.
- Measured runs use a dedicated worker, with the stack worker stopped. The driver restores the original source bytes and checks model, effort, dollar capture, frozen head, chunks, comments, and validator coverage before accepting each run.
- The first medium attempt started at 18:29:13 UTC and was interrupted at 18:42:33 UTC after one of nine review units failed before its first model request. Django auto-reloads during writes under `products/` caused task API callbacks to return HTTP 502; the failed completion callback left that unit active. Eight units completed, but this incomplete attempt is excluded from comparison. Its captured gateway cost was `$0.26832528`, preserved in `runs/luna-medium-1-aborted.ai_usage.json`. All nine sandboxes were confirmed stopped before retrying.
- Django's development server watches all of `products/`, including analysis scripts and experiment artifacts. Its reload option was disabled for the four measured runs and restored after they finished.
- `luna-medium-1` (MA) started at 18:47:28 UTC and passed every acceptance check: 555 seconds, 151 gateway calls costing `$0.54107662`, four chunks, 14 raw issues, 11 post-dedup findings, 11 validator verdicts, and nine kept comments. A separate Kafka partition snapshot reproduced the call count and cost. All 33 fresh votes are complete. Under adjudicated truth it kept three distinct serious issues, one real duplicate, and five not-real comments; precision is 4/9, recall 4/4, and false-finding rejection 2/7.
- MA's fresh panel called the broker-publication loss claim real (MA8, 3/3), while the existing panel rejected that same sub-claim. The adjudicated score retains the existing rejection, with both verdicts preserved. The existing panel also sets MA1/MA6/MA7 to `should_fix` rather than the fresh `must_fix`; these remain serious. All five carryover mappings were checked independently against their original donor claims.
- `luna-medium-2` (MB) started at 18:59:30 UTC and passed every acceptance check: 710 seconds, 155 gateway calls costing `$0.64017952`, four chunks, 15 raw issues, 11 post-dedup findings, 11 validator verdicts, and ten kept comments. A separate Kafka partition snapshot reproduced the cost and count. All 33 fresh votes are complete. Under adjudicated truth it kept three distinct serious issues, one minor issue, one real duplicate, and five not-real comments; precision is 5/10, recall 5/5, and false-finding rejection 1/6.
- MB's fresh verifiers rejected the single-reviewer gate claim (MB2, 3/3), while the existing panel calls its matching sub-claim real. They accepted the broker-publication claims (MB4/MB9, 3/3 each), while the existing panel rejects them. The existing panel also lowers the generic retry-exhaustion claim (MB10) from `should_fix` to `consider`, and MB1/MB7/MB8 from `must_fix` to `should_fix`. All seven carryover mappings were checked independently against their original donor claims.
- An independent audit reproduced all eight completed runs' costs and quality counts directly from raw events, dumps, findings, matches, and truth files. Medium means are `$0.59062807`, 10.54 minutes, 9.5 comments, three distinct serious issues, 0.5 minor issues, and five not-real comments. Pooled noise is 10/19 (53%), validator precision 9/19 (47%), recall 9/9 (100%), and false-finding rejection 3/13 (23%). Both medium sets have three votes and one validator verdict per finding.
- `luna-xhigh-1` (XA) started at 19:14:09 UTC and passed every acceptance check: 2,160 seconds, 529 gateway calls costing `$3.48908028`, four chunks, 32 raw issues, 22 post-dedup findings, 22 validator verdicts, and 20 kept comments. A separate full Kafka partition snapshot reproduced all 529 calls and their cost, with actual Luna effort `xhigh` in review, blind-spot, and validation. Review wave took 16m 46s, blind-spot 6m 13s, Sonnet dedup 3m 33s, and validation 9m 08s.
- XA judging began from a private copy of the 22 sealed post-dedup claims during model validation. The private judge input excluded validator fields. Every id, priority, file, line, title, problem, and suggestion exactly matches the final parsed dump; only those final findings will be scored. Two matchers agreed on 21 findings; an independent tiebreak matched XA13 to cluster 2 for its primary receiver-provenance claim. All 66 fresh votes are complete. Eight panel carryovers were independently checked by sub-claim. Under adjudicated truth, XA kept eight distinct serious issues, two minor issues, three real duplicate comments, and seven not-real comments; precision is 13/20 (65%), recall 13/13 (100%), and false-finding rejection 2/9 (22%).
- XA's fresh judges accept the broker-publication and queue-time toggle claims (XA5/XA10), which the original panel rejects. The panel also lowers XA2/XA7/XA9/XA13 from `must_fix` to `should_fix`, and XA18's stranded-QUEUED claim to `consider`. XA3 and XA15 retain the same minor replica-lag readiness defect in all six fresh votes; an independent source audit confirmed this overlap. An explicit finding-specific group counts them as one minor issue and one real duplicate, preserving both original matches and verdicts.
- `luna-xhigh-2` started at 19:53:17 UTC and completed in 2,185 seconds: nine review units, four blind-spot units, 27 raw findings, 22 deduplicated findings, 22 validator verdicts, and 19 kept comments. Its 546 captured requests comprise 537 priced generations costing `$3.15126478` and nine validation HTTP 404 events with null usage/cost fields. The strict driver check failed on those nulls at 20:32 UTC, after the completed review; all three temporary source edits were restored and the dedicated worker stopped. A separate, hash-bound accounting acceptance follows the independent audit described below, without rewriting the failed driver log.
- XB judging began from a claims-only snapshot whose final parsed claim fields match exactly. Two matchers agree on 21 findings; a third keeps XB18 unmatched because its primary receiver guard differs from cluster 1's webhook lookup. All 66 fresh votes are complete. Eleven panel carryovers were independently checked. Adjudicated XB posts eight distinct serious issues, one minor issue, four real duplicates, and six false comments: precision 13/19, recall 13/14, and false-finding rejection 2/8.
- XB2/XB13's queue-time-toggle claims and XB5's broker-publication claim take the panel's false verdict despite fresh real verdicts. XB19 takes the panel's real single-reviewer verdict despite fresh rejection; the model validator rejected it too. XB7's compound claim preserves the panel's rejection of broker failure and separately retains the unanimous fresh `should_fix` process-exit sub-claim that the original panel did not cover. The carryover script validates that exception explicitly. Other carried severities follow their matching panel sub-claims.
- A complete independent Kafka snapshot matches all 546 XB records exactly. Installed LiteLLM 1.92.0's HTTP and exception paths classify the nine captured errors as HTTP 404 before a response stream starts. No successful generation lacks cost. The raw nulls remain unchanged, and `runs/luna-xhigh-2.request_errors.json` records the per-event evidence and limits. Reported dollars sum priced generations; rejected attempts are not imputed as zero and no provider-invoice reconciliation is claimed. The scorer still rejects missing prices outside the exact audited error ledger.
- The final independent audit reproduces all ten runs' numeric results directly from raw events, dumps, findings, matches, duplicate groups, and truths. Xhigh means are `$3.32017253`, 36.21 minutes, 19.5 comments, eight distinct serious issues, 1.5 minor issues, 3.5 real duplicates, and 6.5 false comments. Pooled noise is 13/39 (33%), precision 26/39 (67%), and recall 26/27 (96%). All 198 new votes and all 66 validator verdicts are present.
- A separate pricing audit finds identical observed base Luna token rates across all six Luna runs. Forty-nine xhigh calls enter a higher context-price tier, adding `$0.32536628` to the mean xhigh cost. Removing that increment still leaves xhigh at `$2.99`, ten times low. Both runtime commits pin LiteLLM 1.92.0; the gateway analytics dependency changes from 7.54.0 to 7.54.1.
- Updated recommendation in `FINAL_REPORT.md`: medium is the budget choice, buying twice low's serious-issue yield for an extra `$0.29` per review; xhigh is the coverage option at `$3.32`, eight serious issues, and 33% noise. Neither validator rejects most false candidates. All ten fresh/adjudicated scorecards, comparisons, and sensitivity modes are regenerated. The report distinguishes counts of distinct serious issues from per-finding sensitivity results.
- Xhigh's larger event payloads exceeded the live monitor's 15-second Kafka read budget. The capture services remained healthy and the events were retained. Extending the monitor's read deadline produced a complete snapshot of 368 calls costing `$2.10787712` at 19:36:49 UTC, with no missing costs or model/effort mismatches. This was a monitoring timeout, not a failed review or missing cost capture.
- New findings require three fresh verification votes, including findings on the settled registry list, to match the completed baseline protocol. Existing panel verdicts transfer only through explicit matching sub-claims in a carryover file: `{"MA1": {"source_id": "UA7", "reason": "Same receiver provenance sub-claim."}}`.
- Scoring scripts now separate a missing validator verdict from a rejection. This corrects GC's automated rejection count to 18/27 plus one missing verdict, matching the existing final report.
- Cost scoring now sums unrounded raw gateway events, excluding capture probes; the GLM composite uses its documented source stages. This corrects earlier per-run rounding artifacts, including Luna low2's `$0.31` to `$0.30` and Sol low1's `$6.59` to `$6.58`, without changing the rounded baseline arm means.
- Final cleanup verified all 67 measured-run sandboxes stopped, restored all three temporary source files and the backend launcher byte-for-byte, restarted the shared backend and Temporal worker, and confirmed both health endpoints. The temporary owner-only Modal credential copy was deleted after those checks. No PR comments or reviews were published.
- Independent report review reproduced all ten outcome tables, sensitivity cells, token-price calculations, and cost totals. It corrected the distinction between omitted captured token fields and zero counters in the usage collector, and the receiver's internal-task guard label. Markdown formatting, Python lint, and the numeric audit pass. The existing Flash API change already has matching generated enum/schema outputs; no API generation change is needed for this results-only increment.

## Decisions (grilled 2026-09-16)

1. **Shape:** the existing pipeline, unchanged. Only the reviewer arm (perspectives + blind-spot sweep) and the
   validator run on GLM. Chunking, perspective selection, and dedup stay on the Sonnet one-shots. No sandbox-free
   one-shot review (rejected: it is a different product, not a cheaper version of this one).
2. **Model:** `zai-org/glm-5.3-flash` @ `high` in both seats (the GLM family only exposes `high` and `max`; the
   August runs used `max`). One shared arm constant, `FLASH_ARM` in `reviewer/constants.py`.
3. **Skill delivery: the pinned skill body is pasted into the prompt for Flash turns** (`skill_body` on
   `build_review_prompt` / `build_validation_prompt`, loaded by `load_skill_body`; the templates branch on it).
   The first plan kept the MCP pull and checked it in the local run; the August finding held (L3 below: every GLM
   sandbox searched for `skill-get`, found only `exec`, and reviewed blind), so the agreed fallback is built. Full
   turns still pull over MCP, unchanged.
4. **A per-run switch, not a tier.** The UI trigger sends `run_mode=flash`; the workflow input carries
   `review_mode`; the review and validation activities pick their arm by it. The PR's stored tier and arm are
   untouched, so a later normal trigger runs a normal review.
5. **One review per commit, whichever came first.** The existing join-on-running and already-reviewed rules cover
   Flash in both directions. The per-commit reviewer-result cache is stamped with the model that wrote it and only
   reused by the same model, so a full review after an empty Flash run at the same commit cannot silently reuse
   GLM's results and skip Sol.
6. **Trigger:** the "Review in Flash mode" item in the Code review scene's split button only. No label, inbox, or
   CLI variant (the MCP trigger tool shares the endpoint and inherits the choice).
7. **Prefix:** every GitHub message a Flash run writes starts with `FLASH MODE` + newline: the status comment
   (all edits), the one-time promo comment, the review body, and every inline finding comment.
8. **Never writes code:** the resolution stage is off for Flash, whatever the user's `resolve_comments` setting
   says. The trigger pins it off and the workflow refuses the dispatch for a flash turn.
9. **Telemetry:** `review_mode` on the started / completed / failed events; the reviewer and validator model
   properties come from the same mode-aware helpers the pipeline uses. Nothing stored on the report row. The
   per-finding outcome event (classified hours later, without the turn's mode) is left alone.
10. **Prod plumbing:** GLM 5.3 Flash added to the worker's `review_hog` scoped-token allowlist
    (`products/tasks/backend/temporal/process_task/ai_gateway_token.py`) AND to the Python gateway's
    `background_agents` allowlist (the mint-failure fallback path; a frozen service, justified as an active-caller
    fallback).

## Checks before the 100 PRs

1. **Local run (DB-only):** start the flash workflow with publishing off against the frozen PR 75215 and confirm in
   the agent log (`task_run.log_url`) that every GLM unit fetched its skill (`skill-get` / `exec skill get` call
   before analysis). If it did not, switch to inline skill delivery before any prod run. **Outcome: it did not
   (L3), inline delivery built; L4 re-checks that the inline body is in the prompt and the run completes.**
2. **First prod Flash run:** confirm the Go ai-gateway actually serves `zai-org/glm-5.3-flash` in prod (Baseten
   host wired) — a served-but-unpinned model is denied with no fallback, and an unserved entry is dropped from
   the token pin by a current gateway binary or fails the whole mint on an older one (which then falls back to
   the Python gateway, where the patched `background_agents` allowlist takes over). Watch `AI_GATEWAY_TOKEN_MINTS`
   and the first unit's `$ai_model`.

## WORK TO DO (kept current so a compacted session can resume; check off as done)

Goal: find the cheapest + fastest Flash arm with good-enough quality. **A run without dollar figures has no value.**

1. [x] **Cost capture must work before any run.** DONE 21:50 UTC: `capture-ai` added to the slim stack (Alex restarted), the proxy answers 200 on `/i/v0/ai/batch/`, and the `events_plugin_ingestion_ai` topic holds real gateway `$ai_generation` rows with `$ai_total_cost_usd` + tokens. Side note: Modal sandboxes of a terminated Temporal workflow keep running (and billing) until they finish on their own. Root cause found 2026-09-16 ~21:40 UTC: this slim dev stack runs no
       `capture-ai` service, so the proxy (`localhost:8010`, Caddy in docker) answers 502 for every capture and the
       gateway's `$ai_generation` events land nowhere. Fix in progress: add `capture-ai` (the docker image
       `ghcr.io/posthog/posthog/capture:master`, host port 3309, feeds Kafka `events_plugin_ingestion_ai`, the topic
       `kafka_ai_usage.py` reads) to Alex's slim hogli stack (`~/Documents/Code/posthog_configs/slim-stack/`), Alex
       restarts `hogli start`. Keep `LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE=true` (now in `.env`, which the gateway launcher
       sources). Then PROVE it: one tiny gateway call → the `_ai` topic count goes up (see `probe.json` / gateway-call
       recipe in the session scratchpad; recreate if lost: POST `$ai_generation` to `http://localhost:8010/i/v0/ai/batch/`
       with team 1's `api_token`, then one `/review_hog/v1/messages` call to `zai-org/glm-5.3-flash` with the local
       personal API key, then count messages in `events_plugin_ingestion_ai`).
2. [x] **Six clean-room runs, one driver:** (DONE 04:00 UTC 09-17; GLM run 1 = composite `glm-high-1bc`) `glm-high` ×2, `luna-low` (gpt-5.6-luna @ low, full-access) ×2,
       `sol-low` (gpt-5.6-sol @ low, full-access) ×2; same model in both seats; harness = August clean room (pinned 4
       chunks via `REVIEWHOG_EXPERIMENT_PINNED_CHUNKS=<2026-08-model-glm53-flash/pinned_chunks.json>` exported into
       the worker, `fetch_pr_comments → []`, `MAX_CONCURRENT_SANDBOXES = 4`) + inline skills; `FLASH_ARM` swapped per
       arm in `reviewer/constants.py`; report row for PR 75215 deleted before each run; own worker restarted per arm
       (no hot reload; `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` unset in its shell); 150-min cap; per run: `runs/<run>.log`,
       `.start/.end` epochs, `dump_result.py` md, `kafka_ai_usage.py` → `.ai_usage.json` + `.usage.md`,
       `summarize_run.py` → `.summary.txt`. Driver + helpers live in the session scratchpad (`overnight_driver.sh`,
       `set_arm.py`, `harness_apply.py`, `summarize_run.py`, `run_flash_local.py`); if lost, rebuild from this description.
       First attempt (21:07 UTC) was stopped: no cost data (item 1). Its partial `runs/glm-high-1.*` files are void.
       **Second attempt (21:44 UTC): `glm-high-1` FAILED at dedup** (`One-shot dedup LLM call failed: AuthenticationError
(status=401)`, 44 min, $1.12 of GLM review+blind-spot spend recorded). Root cause: the worker's direct gateway calls
       (selection, dedup — `settings.LLM_GATEWAY_API_KEY` = the local dev key) use a key whose scopes are `['*']`, and the
       gateway's `has_required_scope()` does not accept the wildcard by default (`allow_wildcard=False`), so every
       personal-key call is 401 while sandbox OAuth calls pass. The launcher's `setup_local_api_key --add-scopes
llm_gateway:read` reported "already present" and added nothing. Fix applied 22:38 UTC: the dev key now carries
       `['*', 'llm_gateway:read']`; the gateway's 15-min negative auth cache must expire (or the gateway restart) before
       it takes effect. Consequence for the run that failed: selection had ALSO been failing open (dense 12 units, no
       `perspective_selection` artefact), which is the same August "dense" shape. `glm-high-1` must be re-run; the driver
       continued into `glm-high-2` (its wave started 22:29 UTC, before the fix) — its dedup runs after the cache expiry,
       so it should pass; if it does not, re-run it too. Worth a `hogli devex:feedback -c bug` in the morning.
       A chained re-run of the GLM arm (`glm-high-1b`, via `rerun_driver.sh` + `chain_rerun.sh` in the scratchpad) starts
       automatically when the six-run driver logs `DRIVER DONE`, and logs `RERUN CHAIN DONE` when finished.
       **Source of truth per run = the `dump_result.py` markdown (`runs/<run>.md`, funnel table + per-finding verdicts) and
       `runs/<run>.usage.md` (gateway cost by stage).** The `.summary.txt` files from before 00:05 UTC undercount kept
       verdicts (script bug, fixed 00:05); the dump's "Config snapshot" shows the REPORT's stored arm (Sol xhigh), not the
       flash arm the units ran — read the true arm from `.usage.md`. Interim numbers: `glm-high-2` 71 min, raw 55 → dedup
       35 → **14 kept**, ≈$2.41; `luna-low-1` 14 min, raw 9 → dedup 9 → **8 kept**, ≈$0.30; `luna-low-2` 16 min, raw 8 →
       dedup 8 → **7 kept**, ≈$0.31 (Luna @ low finds little and keeps almost all of it — the judge decides if it is real).
       `sol-low-1` 20 min, raw 11 → dedup 9 → **7 kept**, ≈$6.59 (review $3.31, blind-spot $1.47, validation $1.70) —
       about 20× Luna's price for a similar funnel.
3. [x] **Judge (multi-agent workflow approved by Alex):** (DONE ~07:30 UTC 09-17 → `FINAL_REPORT.md`: pick GPT 5.6 Luna @ low; drop GLM; Sol @ low = quality fallback; report fact-checked by workflow `wf_58170a2f-b64`: 242 numbers/claims checked, 6 small errors found and fixed, recommendation unchanged) per run, dump → `parse_dump.py` → match findings to the
       76-cluster registry (`2026-08-validator-model-sol/known_clusters.json`) → refutation-first fresh verification of
       unmatched claims → `findings/<SET>.{json,match.json,score.md}` like RA/RB → validator confusion + coverage (findings
       with NO verdict) → cost per stage and per verdict → `FINAL_REPORT.md` ranking the three arms on cost, time, real
       findings, validator recall/precision, and naming the best Flash arm. August references: RA/RB (GLM max),
       K/P (Sol low/medium), L/M/N (validators) in the two 2026-08 experiment folders.
       **State 00:50 UTC 09-17:** sets parsed: `GB` (glm-high-2), `UA`/`UB` (luna-low-1/2), `SA` (sol-low-1); `SB`
       (sol-low-2) and `GA` (glm-high-1b) still running. Judge workflow `wf_f4f4f37d-e94` (script `flash-arm-judge`, Match
       = 2 matchers + tiebreak, Verify = 3 refutation-first skeptics) is running on GB/UA/UB/SA — launched with the WRONG
       `settled` list for GB (all 76 clusters), so GB findings matched to a non-unanimous cluster come back without a
       verdict. Recovery recipe: save the workflow's returned JSON to `findings/judge_result_1.json`; run
       `python3 scripts/assemble_truth.py findings/judge_result_1.json` → it writes `<SET>.match.json`/`.truth.json` and
       PRINTS the PENDING (fid, cluster) pairs; feed those to the follow-up workflow `scratchpad/verify_pending.js` (args
       `{worktree, items:[{letter, findings, id, cluster}]}`) → save to `findings/verify_result_1.json` → re-run
       `assemble_truth.py findings/judge_result_1.json findings/verify_result_1.json`. Unanimous clusters (the only ones
       whose registry verdict is trusted) = `findings/settled_clusters.json` = [3,4,9,13,31,35,59,61]. Then judge SB and GA
       with the same `flash-arm-judge` script and that settled list. Scorecards: `python3 scripts/scorecard.py <SET> <run>`
       → `findings/<SET>.score.md` (funnel, reviewer real rate, validator precision/recall, coverage, $ per stage/verdict).
       Frozen worktree for verification: `/Users/woutut/.worktrees/posthog/frozen-75215` at `a7fb363bef69`.
       Repo hygiene: the scripts write plain markdown tables, so run `hogli format:markdown 'products/review_hog/eval/experiments/2026-09-flash-mode/**/*.md'` after regenerating anything, or the
       pre-push oxfmt check fails. The parsers tolerate the padded tables the formatter produces.
       01:00 UTC: `sol-low-2` done (21.5 min, raw 14 → dedup 10 → 7 kept, ≈$7.43) → parsed to `SB`; judge workflow
       `wf_f7285e1c-657` launched on SB with the correct settled list (script copy: `scratchpad/flash_arm_judge.js`).
       `glm-high-1b` re-run started 00:56 UTC (expect ~70 min) → parse to `GA`, judge the same way.
       **01:30 UTC judge-consistency decision:** the fresh 3-skeptic panel is more lenient than August on some clusters
       (58 "broker failure loses the initial review" was 1/6 real in August, now 4 of 6 fresh verdicts say real; 31 was
       0/6 settled not-real, UB8 came back real 3/3; 57 was 2/11, SA7 real 2/3). Mixing registry verdicts (GB's 5
       settled-cluster findings) with fresh verdicts (every other set) would judge the same claim two ways inside one
       experiment. Rule from here: **every finding of every set gets the same fresh 3-skeptic verdict; the registry is
       only a matching aid plus a calibration note in the report** (fresh vs August per cluster). Follow-ups launched:
       `wf_0ae1b5bf-2c6` (17 GB non-unanimous), `wf_ebf7f32b-c79` (5 GB settled-cluster findings). SB's judge ran with
       the settled list, so SB findings matched to [3,4,9,13,31,35,59,61] need the same follow-up; GA's judge runs with
       `settled: []`. Sensitivity check for the report: cluster-pooled majority (all fresh votes on a cluster across sets).
       **03:40 UTC:** `glm-high-1b` FAILED at validation (66 min, raw 46 → dedup 36, 0 verdicts, ≈$1.40 spent): all 4
       validation sandboxes died with `SandboxProvisionError` ← Modal `ImageBuildError` "no Go files in /src" at the
       Dockerfile's agent-shadow `go build` step. Cause: at 01:35:05 UTC something deleted README.md/main.go/main*test.go
       (kept go.mod) from `products/desktop/packages/agent-shadow/` in EVERY local Modal build context under
       `/var/folders/.../T/posthog-modal-build-default_base-*`(16 dirs, one or two per worker start); the 300-s TTL cache
       on`get_template_base_image`re-hashed the mutilated context → new image id → real build → failed. Sweeper not
       identified (not a judge agent: their transcripts only grep the source line). Trap for the record: any process that
       touches those temp dirs breaks every later sandbox until the worker restarts. Reviewer-side data for the run is
       fine → parsed to`GA`(36 findings,`is_valid`all False); judge`wf_9e329ec2-fbe`launched with`settled: []`.
       Validator-side recovery: `scratchpad/rerun_validate.sh` (= rerun_driver.sh without the report-row delete) re-runs
       the flash workflow on the SAME report so the model-stamped per-commit reviewer cache is reused and only dedup +
       validation run (`glm-high-1c`); its verdict set is re-deduped, so map its findings to GA by (file, title) and verify
       only the unmatched ones. Judge 2 (SB) + follow-ups saved as `findings/judge_result_2.json`, `verify_result_2.json`       (GB settled 5),`verify_result_3.json`(SB1, SB9); SB truth complete (10/10 fresh).
       **06:30 UTC state — all six runs have data, all six sets fully judged (fresh 3 votes on every finding).**
      `glm-high-1c`(validation-only re-run, 03:22–04:00 UTC) succeeded: 46 → 36 → 13 kept, dedup $0.12 + validation
       $1.26; its 36 findings are identical (file, title) to 1b's, so run 1 of GLM = set`GC`= composite run
      `glm-high-1bc` (`runs/glm-high-1bc.{md,usage.md}`: reviewer side from 1b, dedup + validation from 1c, $2.56,
       83.5 min). Judge files: `judge_result_1.json`(GB/UA/UB/SA),`judge_result_2.json`(SB),`judge_result_3_partial.json`       (GA matching; most verifiers died when usage credits ran out) +`verify_result_1..4.json`(GB 17 + GB 5 + SB 2 +
       GA 31 re-verifications). Scripts:`scorecard.py`, `compare.py`→`findings/COMPARE.md`, `sensitivity.py`→
      `findings/SENSITIVITY.md`. **The ranking flips with the truth rule** (fresh: Sol best quality; August-anchored: Sol
       drops to Luna's level; must/should only: GLM collapses), because clusters 58/39/31/57 (and 10 smaller ones) are
       judged differently by August and by the fresh panels, and inconsistently inside this experiment (7/33 clusters).
       Resolution in flight: dossiers `findings/adjudicate/cluster\*<c>.json`(July/August verdicts + current findings +
votes) → workflow`wf_572601b5-0f8`(3 adjudicators per contested cluster: own-view / steelman-real /
steelman-not-real, per-finding majority, shared sub-claims must share a verdict) → save to`findings/adjudication_result.json`→`python3 scripts/apply_adjudication.py findings/adjudication_result.json`→`sensitivity.py`gains modes E/F → write`FINAL_REPORT.md`(primary truth = adjudicated E; show A/C/D as
sensitivity). Cleanup left: phrocs`temporal-worker`OFF, PR 75215 report row still in local DB,`.env`
`LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE=true`, temp build-context sweeper unidentified.
Judge 1 result saved: `findings/judge_result_1.json` (GB 35 matched / UA 9 / UB 8 / SA 9). Scorecards written for
UA, UB, SA (`findings/<S>.score.md`): Luna low ≈ $0.30, 14–16 min, 2/9 and 4/8 real, validator keeps almost
       everything (precision 25% / 57%); Sol low ≈ $6.59, 20 min, 7/9 real, validator precision 100%.
4. [ ] **Cleanup (partly done):** harness + arm reverted by the driver (git clean apart from the experiment folder), own worker stopped, phrocs `temporal-worker` toggled back ON (~07:30 UTC 09-17). Still open: revert the harness + arm edits (`git checkout -- constants.py activities.py github_meta.py` — the
       committed flash mode `810ab275ccb` is safe), toggle the phrocs `temporal-worker` back on (or Alex restarts hogli),
       stop the own worker, delete the PR 75215 report row, note the `.env` capture flag left `true`.

## Run log

### L1 — local DB-only flash run (2026-09-16, started 18:16:38 UTC)

- Started from a Django shell (`execute_review_pr_workflow(..., publish=False, review_mode="flash")`, team 1 / user 1 /
  acting user 1) against PR 75215 at `a7fb363bef69` (the PR is closed since August; its branch still exists and the
  direct workflow path has no open-state gate). Report `01a0ab6f-6f76-7f26-9e76-2c4397788d61`. Stored arm untouched
  (`review_tier=human`, `review_model=gpt-5.6-sol`) — the per-run switch leaves the row alone as designed.
- Chunking: 2 chunks (unpinned, unlike the August clean room), selection persisted, 6 review units
  (3 perspectives × 2 chunks) started 18:19:29 — every `TaskRun.state` reads `claude / zai-org/glm-5.3-flash / high`.
- Ops: the worker in this stack does not hot-reload `.py` edits (restart via phrocs before a run); the local
  llm-gateway needed a restart to pick up the `background_agents` allowlist; `create_sandbox_for_repository` ran with
  `image_source=modal_local_build`, i.e. a cold local image build (~20 min) before the agents started.
- **FAILED at agent start, both parent attempts (30 sandboxes, zero LLM calls):** every sandbox died with
  `POSTHOG_CODE_REASONING_EFFORT 'high' is not supported for claude model 'zai-org/glm-5.3-flash'`. Cause: the local
  image was built from `LOCAL_POSTHOG_CODE_MONOREPO_ROOT=~/Documents/Code/code`, the pre-migration agent checkout
  (last commit 2026-08-01), whose registry predates GLM 5.3 Flash. Not a prod problem: the published
  `@posthog/agent@2.4.187` (2026-09-16) lists `["high", "max"]` for the model, and so does this repo's generated
  catalog. Fix for the local run: the `.env` line is commented out (published agent in the local image), the
  workflow was terminated, the worker restarted, and the run relaunched as L2.

### L2 — same failure (started 18:53:57 UTC): the stack's worker keeps its environment

- Identical `'high' is not supported` on every sandbox, 6/6 units failed → failure floor → run failed. `hogli start`
  loads `.env` once into the phrocs daemon and every process restart inherits that snapshot, so commenting the line
  out and toggling the worker changed nothing. (The stale checkout has built `dist/` dirs, so the local packages
  really were baked.)

### L3 — own worker without the variable (started ~19:35 UTC)

- The phrocs `temporal-worker` is stopped for the duration and an identical worker (the `bin/mprocs.yaml` command,
  `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` unset) runs from the session scratchpad (`run3_chain.sh`, log
  `own_worker.log`); the phrocs worker goes back on afterwards. The image now installs the published agent.
- **Started 19:22:27 UTC; agents ran.** 2 live chunks, 6 wave units done in 7–13 min each (all on
  `claude / zai-org/glm-5.3-flash / high`), 2 blind-spot units 12–15 min, dedup → 23 findings, GLM validation from
  19:54.
- **Skill fetch: NO.** Every GLM unit ran `ToolSearch("select:mcp__posthog__skill-get")`, got no match (the
  `posthog` MCP is exec-only for non-allowlisted clients; a `posthog-local` MCP entry from
  `POSTHOG_DESKTOP_SKILLS=local` was unreachable from Modal), never called `exec`, and reviewed blind — the August
  finding holds. Tools it did use: `Execute command`, `Read File`, `ToolSearch`. → inline skill delivery built
  (decision 3), exercised by the next run.
- **GLM validator warm-session death (the August V2 signature, now explained):** `validation-c1` failed on a
  follow-up turn with a gateway 400, `messages.17: role 'system' must precede an 'assistant' message or end the
array` — the claude adapter's follow-up turn puts a system-role message mid-array, which the GLM (Baseten)
  Messages surface rejects. The chunk retried with skip-resume (`VALIDATION_MAX_ATTEMPTS = 2`); a repeat on the
  final attempt skips the issue, i.e. a coverage hole. Open question for the 100-PR test: how often it recurs, and
  whether the flash validator should run one session per issue instead of a warm session.
- **Done 20:57:09 UTC, wall 5682 s (95 min), DB-only, no cost figures** (the local gateway had
  `LLM_GATEWAY_POSTHOG_AI_LANE_CAPTURE=false`, so no `$ai_generation` events landed anywhere). Funnel: raw 25
  (wave 21 + blind-spot 4) → dedup 23 → valid **unknown** (my ad-hoc summary script miscounted verdicts as 0 kept —
  disproven by the dumps of later runs — and this report row was reset before a dump was taken); both validation
  chunks died once on the 400 above, retried, and every finding got a verdict (23/23, no hole). Unit times on GLM @ high: wave 6.6–13.1 min, blind-spot 11.6–14.9,
  validation-c1 retry 8.5 min for its share, validation-c2 retry **51 min** (one warm session grinding through 14
  findings; the validator is the slow seat). Both seats ran blind (no skill), so this is a mechanics run, not a
  quality number.
