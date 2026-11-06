# PLAN — GPT-5.6 Sol as the ReviewHog validator

**Question:** does `gpt-5.6-sol` (Codex) match Claude Opus as the validation model, at lower cost and time?
Same frozen PR and harness as the reviewer-model experiment (`../2026-07-reviewer-model-glm52/`), so the
known-issue registry and judge verdicts there are the ground truth here.

## Decisions (grilled 2026-08-25)

1. **Control:** the existing Sol runs I1/I2 (Sol reviewer + `claude-opus-4-8` validator). Opus 4.8 and Opus 5
   are treated as the same validator (no noticeable difference observed when the pin moved on 2026-08-12).
   Option B (fresh Sol + Opus 5 control runs) only if the result is ambiguous.
2. **Runs:** two GPT+GPT runs (Sol reviewer, Sol validator), serial, no publish, team 1 / user 1.
3. **Validator pin:** `codex` / `gpt-5.6-sol` / `xhigh` / `full-access` — the same config the reviewer runs on.
4. **Scoring:** match each new finding to the known issues (76 clusters, `judge-round5/6.json`); reuse their
   real / not-real verdicts; verify only unmatched findings. Per validator: of the real findings, how many kept;
   of the not-real, how many dropped. Opus's numbers come from I1/I2 for free.
5. **Harness:** comments mocked to none, chunks pinned from `pinned_chunks.json`, arm = default Sol (no change),
   between runs delete only the PR 75215 report (not the global wipe). All hacks reverted after the runs.
6. **Results live here** (PLAN, FINAL_REPORT, `runs/`, `scripts/`), pointing at the old folder's judge files.

## Preconditions found and fixed first

- **Codex multi-turn works.** `scripts/codex_mts_smoke.py`: one Codex session, three turns; the thread keeps
  its history across follow-ups (secret word recalled; 10 s / 30 s follow-up turns).
- **Sandbox MCP was refused since 2026-08-13** (`REVIEW_MCP_SCOPES` lacked `user:read`, which the MCP server
  needs to open a session) — every ReviewHog session ran without its skill. Fixed in #88697; verified by the
  smoke test (`skill-get` returns the validation skill on a follow-up turn).
- **Local sandbox image build broke on master 2026-08-25** (#88274 added a `COPY` the local build context
  lacked). Fixed in #88698.

## Experiment hacks (uncommitted, revert after)

- `tools/github_meta.py::fetch_pr_comments` → `return []`.
- `temporal/activities.py::split_chunks_activity` → load `pinned_chunks.json` when present.
- `reviewer/constants.py` `VALIDATION_*` → codex / gpt-5.6-sol / xhigh / full-access.

## Run recipe

```bash
flox activate -- bash -c "DJANGO_SETTINGS_MODULE=posthog.settings python manage.py \
  run_review --pr-url https://github.com/PostHog/posthog/pull/75215 --team-id 1 --user-id 1"
LABEL=K-sol-validator-1 RUN_SECONDS=<s> RUN_START_EPOCH=<epoch> OUT_DIR=$PWD/runs \
  python manage.py shell -c "exec(open('products/review_hog/eval/scripts/dump_result.py').read())"
```

## Run log

- **K1 (2026-08-25 19:44–20:04 local, 1191 s):** report `01a03a06-2d2e-73a7-9e7c-1ab81a3b3651`, head `a7fb363b`. 4 pinned chunks, selection kept 8 review units; 16 raw → 14 dedup → 5 valid. Review wave 3m17s; blind-spot 10m08s (c4 first attempt died at boot, retry cleared — the known Codex boot hiccup); dedup 49s; **validation 4m58s** (4 sessions, 14 turns: 7/3/1/3; 176–323 s each). Cost from agent logs (`runs/K-sol-validator-1.usage.md`, gateway rates): validation $0.93, review $0.68, blind-spot $0.27; one-shots not counted. Local `$ai_generation`telemetry was down (ingestion consumer blocked on personhog :50052), so`dump_result.py`'s spend table is empty for this run.
- **K1 is a "wrong tree" run.** Its validator reasoning cited code that exists only on master (`facade/api.py:694-747`,
  `test_webhooks.py:2000-2061`) and the sandbox's own `git rev-parse HEAD origin/master` returned the same commit
  (`def397d7`, master's tip that day): the Tasks checkout cannot resolve the `pull/N/head` ref ReviewHog passed since
  2026-07-15 and fell back to a fresh branch on master. Fixed by checking out the head branch by name
  (branch `reviewhog/fix-sandbox-checkout-head-branch`, merged into the experiment tree). K1 stays in the report as the
  before/after data point for that fix; its validator numbers describe Sol judging the wrong tree.
- **K2 (2026-08-25 20:33–21:02 local, 1691 s):** report `01a03a33-78b6-79ea-a35b-d97a111c082c`, head `a7fb363b`,
  sandboxes checked out `stamphog-inbox-prs-experiment-frozen`. 8 review units; 14 raw → 10 dedup → 8 valid. Review
  wave 3m36s; blind-spot 3m07s (no boot retry); dedup 1m53s; validation stage 18m56s, of which three sessions took
  185–262 s (9 verdicts) and `validation-c4` took 1144 s for one verdict: its sandbox logged "Repository clone failed;
  created empty workspace", so Codex fetched `refs/pull/75215/head` itself and read files over `gh api` before judging
  (KB5, dropped). Cost from agent logs (`runs/K-sol-validator-2.usage.md`): validation $0.72, review $0.54,
  blind-spot $0.24.
- **Scoring (2026-08-25 21:20):** all 24 findings across K1/K2 matched known clusters (no new issues). Mixed-cluster
  findings verified one by one against the frozen worktree (`findings/verify/`): KA4 real should_fix, KA5 not,
  KA6 real consider, KA9 real should_fix, KA10 real must_fix, KA13 not, KB4 not, KB5 not; KB1/KB3/KB6/KB8 reuse the
  KA verdicts for the identical claims, KB7 reuses W11 (July). Scores in `findings/*.score.md`: Opus (S+W, July
  per-finding verdicts) precision 6/6, recall 6/8, not-real dropped 16/16; Sol K1 (wrong tree) 5/5, 5/9, 5/5;
  Sol K2 (PR tree) 4/8, 4/4, 2/6.
- **K3 (2026-08-25 22:44–23:36 local, 3095 s), Sol validator pinned at `max`:** report `01a03aaa-bc4d-7c6d-ba33-20a87f55e8fc`,
  head `a7fb363b`, sandboxes on `stamphog-inbox-prs-experiment-frozen`. 9 review units (selection kept one more than K1/K2);
  10 raw → 7 dedup → 6 valid. Review stage 35m55s: 4 of 9 sandboxes ended their turn with Codex `stopReason=refusal` inside
  one 5-second window (22:46:57–22:47:02) and could not call home ("Failed to signal task completion: fetch failed"), so the
  worker waited the full 1800 s poll timeout before retrying; all 4 retries completed in ~3 min. Blind-spot done by 23:20:39,
  dedup ~1 min, validation 23:21:52–23:36:07: c2 3 verdicts in 200 s, c3 2 in 155 s, c1 2 in 849 s of which ~12 min was
  local Modal sandbox provisioning (agent server initialized at 23:34:09); judging time per verdict 30–70 s, same as K2.
  TaskRun state confirmed `codex / gpt-5.6-sol / effort=max / full-access`.
- **Scoring K3 (23:45):** all 7 findings matched known clusters (`findings/KC.match.json`); five are the exact claims K2 made
  (KC2=KB1, KC3=KB3, KC4=KB4, KC5=KB2, KC6=KB6, KC7=KB8), KC1=KA3. Truth reuses the same-claim verifications
  (`findings/KC.truth.json`). Score (`findings/KC.score.md`): kept-real 3/6, real-kept 3/3, not-real-dropped 1/4 — the same
  three false keeps as K2. Blind write-up judge K3 vs K2 (`findings/argumentation_judge_K3_vs_K2.json`): no improvement.
- **Costs re-measured at the gateway (23:50).** The `$ai_generation` events sit unconsumed in the local Kafka topic
  `events_plugin_ingestion_ai` (ingestion is blocked on personhog); read directly (`scripts/kafka_ai_usage.py`). Validation:
  K1 $3.39 (79 calls), K2 $2.53 (67), K3 $1.44 (37) at the gateway's LiteLLM rates. The agent-log method
  (`usage_from_logs.py`, since removed) undercounts 3–4× because the ACP per-turn usage is the last LLM call of the turn, not the sum of
  its tool round-trips. FINAL_REPORT.md uses the gateway numbers.
- **Effort never reached Codex (00:10, 2026-08-26).** Every `gpt-5.6-sol` call in K1, K2 and K3 carries `$ai_effort=low`
  (the gateway reads it from the request's `reasoning.effort`); the Sonnet one-shots carry `xhigh`. Same in prod: 100% `low`
  for `background_agents` every day since at least 2026-08-04. See FINAL_REPORT.md "The effort pin never reached Codex".
- **Fix smoke (2026-08-26 00:30–00:38):** patched the installed `@posthog/agent` 2.4.86 inside the local sandbox image (one
  `sed` in `Dockerfile.sandbox-base`, local-only hack) so `collaborationModeForTurn()` carries `reasoning_effort: this._effort`,
  then ran `scripts/codex_mts_smoke.py` (codex / gpt-5.6-sol / xhigh). All 3 turns passed; the gateway saw `$ai_effort=xhigh` on
  all 12 Codex calls (`runs/fix-smoke.gateway_events.json`). Before the patch every Codex call in K1–K3 carried `low`.

## Run log — runs at real `xhigh` (2026-08-26, after the effort fix)

Harness additions for these runs (local hacks, on top of the three above): the sandbox image carries the effort
fix (`Dockerfile.sandbox-base` sed on the installed `@posthog/agent`, now 2.4.87), a second sed that gives codex
`stream_max_retries=10` / `request_max_retries=10` and a 300 s stream idle timeout, and `MAX_CONCURRENT_SANDBOXES`
10 → 4. Arm L = prod validator pins (`claude` / `claude-opus-5` / `xhigh`), arm M = `codex` / `gpt-5.6-sol` /
`xhigh` / `full-access`. Reviewer = Sol at `xhigh` in both arms. The effort guard (`scripts/kafka_ai_usage.py` on
the first review calls and the first validation calls) passed on every run listed below.

- **L1, first attempt (02:34–02:33 local, terminated):** two review waves in a row lost all 8 units the same way,
  ~60 s after the agents started: codex `stream disconnected before completion: error sending request` on the
  gateway tunnel, `willRetry=false`, and the agent's completion signal `fetch failed` on the django tunnel, all 8
  inside 5 s (01:53:47 and 02:24:20). The ngrok inspector shows no sandbox request reaching this machine for ~85 s
  each time (02:23:55–02:25:23), while a Modal probe minutes later reaches all three tunnels in <1 s. Codex retries
  with 200 ms × 2ⁿ backoff, so its default 5 stream retries give up after ~13 s — far short of the outage. This is
  the K3 "bug 6" (4/9 units then); with 8 concurrent xhigh first-requests it hit 8/8. Mitigation: 10 retries
  (~200 s of backoff) + concurrency 4. Two other stalls the same night were self-inflicted: the local Modal image
  build refreshed `products/posthog_ai/dist/skills/*.py` and nodemon restarted the worker mid-build (~70 restarts,
  `SandboxProvisionError`; the same storm crashed the worker with `spawn EBADF` during K3), and one `.py` written
  under `products/` during the run restarted the worker and failed the wave. Rule: no `.py` writes under
  `products/` while a run is in flight.
- **L1 (02:40:39–03:54:53 local, 4432 s):** Sol reviewer `xhigh` + Opus 5 validator `xhigh`. 4 chunks, 8 review +
  4 blind-spot units (concurrency 4, ~6 min image rebuild inside), 28 raw → 23 dedup → **11 valid**. Review stage
  34m26s, dedup 03:15–03:24, validation 03:24–03:54 (4 Opus sessions, 23 verdicts). No turn failures. Gateway:
  review $17.98 (246 calls, 85k reasoning tokens), blind-spot $8.64 (122), validation Opus $20.76 (134 calls) +
  Sonnet helper calls inside the Claude sessions $3.60 (126), one-shots $0.25. Dump `runs/L-opus5-validator-1.md`,
  set `LA` (`findings/LA.json`).
- **M1 (03:57:00–04:38:12 local, 2455 s):** Sol reviewer `xhigh` + Sol validator `xhigh` / `full-access`. 4 chunks, 8 + 4
  units, 24 raw → 19 dedup → **18 valid**. Review stage 25m57s (no rebuild), dedup ~1 min, validation 04:25–04:38 (4 Sol
  sessions, 19 verdicts, ~40 s each). No turn failures. Gateway: review $17.84 (255 calls), blind-spot $7.89 (114),
  validation $13.62 (173 calls, 40.6k reasoning tokens), one-shots $0.15. Dump `runs/M-sol-validator-1.md`, set `MA`.
- **L2 (04:39:56–05:38:08 local, 3491 s):** Sol reviewer `xhigh` + Opus 5 validator `xhigh`. 4 chunks, 9 review + 4
  blind-spot units (selection kept one more, like K3), 26 raw → 22 dedup → **12 valid**. Review stage 28m02s, dedup
  05:07–05:12, validation 05:12–05:38 (22 verdicts). No turn failures. Gateway: review $17.32 (244 calls), blind-spot
  $8.73 (125), validation Opus $23.42 (176 calls), one-shots $0.22. Dump `runs/L-opus5-validator-2.md`, set `LB`.
- **M2 (05:39:43–06:26:54 local, 2792 s):** Sol reviewer `xhigh` + Sol validator `xhigh`. 4 chunks, 9 + 4 units,
  26 raw → 20 dedup → **18 valid**. Review stage 27m35s, validation 06:10–06:26 (20 verdicts). No turn failures.
  Gateway: review $18.50 (276 calls), blind-spot $7.35 (97), validation $15.97 (161 calls, 44k reasoning tokens),
  one-shots $0.22. Dump `runs/M-sol-validator-2.md`, set `MB`.
- **Scoring the four runs (03:55–06:45):** each set matched to the 76 clusters by one agent (`findings/{LA,MA,LB,MB}.match.json`),
  unanimous clusters take the registry verdict, identical claims reuse the K/July verdicts, and 26 mixed-cluster or new
  claims got a fresh refutation-first verification against the frozen worktree (`findings/verify/{LA,MA,LB,MB}*.json`).
  Truth files `findings/*.truth.json`, scores `findings/*.score.md`, four-run table `findings/xhigh_summary.md`,
  reviewer side `findings/reviewer_side.md`, blind write-up judge `findings/argumentation_judge_L_vs_M.json`.
  Helper scripts added: `scripts/build_truth.py` (draft truth from unanimous clusters + list what to verify),
  `scripts/reviewer_stats.py`, `scripts/summarize_runs.py`; the overnight harness scripts sit in `scripts/harness/`
  and the raw operator log in `runs/overnight-2026-08-26.notes.md`. Results and recommendation: FINAL_REPORT.md
  "Runs at real xhigh".
- **Tree state at hand-back (06:45):** `VALIDATION_*` restored to the prod pins; still hacked: the two `sed` lines in
  `Dockerfile.sandbox-base` (effort pass-through + retries/idle timeout), `fetch_pr_comments → []`, the chunk pin in
  `split_chunks_activity`, `MAX_CONCURRENT_SANDBOXES = 4`. No PR 75215 report left in the DB.

## Run log — arm N: Sonnet 5 validator at `xhigh` (2026-08-26 morning, Alex's follow-up)

Same harness as the four runs above (effort fix + retry hack in the image, concurrency 4, comment mock, chunk pin).
Reviewer = Sol at `xhigh`; validator pins = `claude` / `claude-sonnet-5` / `xhigh` / None (arm N). Two runs, sets `NA`, `NB`.

- **N1 (08:40:50–09:32:14 local, 3060 s):** Sol reviewer `xhigh` + Sonnet 5 validator `xhigh`. 4 chunks, 9 + 4 units,
  27 raw → 22 dedup → **16 valid**. Review stage 26m09s, validation 09:10–09:32 (22 verdicts). No turn failures.
  Gateway: review $19.32 (268 calls), blind-spot $6.80 (91), validation Sonnet $9.31 (179 calls) + 6 `claude-opus-4-8`
  sub-agent calls $1.22, one-shots $0.16. Effort xhigh on reviewer and validator. Dump `runs/N-sonnet5-validator-1.md`, set `NA`.
- **N2 (09:33:30–10:30:38 local, 3414 s):** Sol reviewer `xhigh` + Sonnet 5 validator `xhigh`. 4 chunks, 9 + 4 units,
  28 raw → 22 dedup → **22 valid** (nothing dropped). Review stage 27m05s, validation 10:04–10:30 (22 verdicts). No turn
  failures. Gateway: review $17.45 (251 calls), blind-spot $8.18 (117), validation Sonnet $9.35 (197 calls) + 9
  `claude-opus-4-8` sub-agent calls $2.37, one-shots $0.23. Dump `runs/N-sonnet5-validator-2.md`, set `NB`.
  `VALIDATION_*` restored to the prod pins afterwards.
- **Scoring N1/N2 (09:35–10:55):** same protocol; matches `findings/{NA,NB}.match.json`, 5 fresh verifications
  (`verify/NA15, NA20, NB6, NB13, NB14`), truth `findings/{NA,NB}.truth.json`, scores `findings/{NA,NB}.score.md`.
  Sonnet 5 validator: N1 kept 16/22 (kept-real 50%, real-kept 73%, not-real dropped 27%), N2 kept 22/22 (50%, 100%, 0%),
  $0.48–0.53 per verdict. Blind judge N vs L: `findings/argumentation_judge_N_vs_L.json` (Opus 20, Sonnet 2, 7 ties).
  Six-run table `findings/xhigh_summary.md`; FINAL*REPORT.md "Sonnet 5 as validator". Tree state unchanged from the
  hand-back note above (`VALIDATION*\*` on prod pins, the four hacks still in place).

## Run log — arm P: Sol reviewer at `medium`, Opus 5 validator (2026-08-26 afternoon, Alex's follow-up)

Same harness as the runs above (effort fix + retry hack in the image, concurrency 4, comment mock, chunk pin).
Reviewer = Sol at `medium` (`REVIEW_REASONING_EFFORT` flipped to `MEDIUM` before run 1, back to `XHIGH` after run 2);
validator = the prod pins (`claude` / `claude-opus-5` / `xhigh` / None). Two runs, sets `PA`, `PB`.

- **P1 (14:32:16–15:05:37 local, 1963 s):** 4 chunks, 9 + 4 units, 20 raw → 14 dedup → **6 valid**. Review stage
  12m32s, validation 14:48–15:05 (14 verdicts). No turn failures, no worker restarts. Gateway: review $7.43 (121 calls),
  blind-spot $2.80 (44), validation Opus $15.80 (133 calls), one-shots $0.17. `$ai_effort`medium on every reviewer
call, xhigh on the validator. Dump`runs/P-sol-medium-opus5-1.md`, set `PA`.
- **P2 (15:08:26–15:51:39 local, 2582 s):** 4 chunks, 8 + 4 units (the selector pruned one perspective × chunk pair
  this time), 18 raw → 15 dedup → **7 valid**. Review stage 14m03s, validation 15:24–15:51 (15 verdicts). No turn
  failures. Gateway: review $8.46 (134 calls), blind-spot $2.31 (37), validation Opus 5 $12.84 (111 calls) + 2
  `claude-opus-4-8` sub-agent calls $1.06, one-shots $0.09. Dump `runs/P-sol-medium-opus5-2.md`, set `PB`.
  `REVIEW_REASONING_EFFORT` restored to `XHIGH` afterwards; registry test green; report deleted.
- **Scoring P1/P2 (15:15–16:20):** same protocol; matches `findings/{PA,PB}.match.json`, one fresh verification
  (`verify/PB14`, not real), every other claim identical to a verified one (KA2, KA13, KB4, LA6, LA4, NA8, KA10, LA19,
  KA4, KA5, LB4, LB20, W10) → reused. Truth `findings/{PA,PB}.truth.json`, scores `findings/{PA,PB}.score.md`.
  Reviewer at `medium`: 14 / 15 findings, 7 real each (50% / 47%), real clusters 6 / 3, new real 0 (PB5 = LB20).
  Opus 5 validator: P1 kept 6/14 (kept-real 100%, real-kept 86%, not-real dropped 100%), P2 kept 7/15 (100%, 100%,
  100%), $1.13 / $0.93 per verdict. Eight-run table `findings/xhigh_summary.md`, reviewer side
  `findings/reviewer_side.md`; FINAL*REPORT.md "Sol at medium as reviewer". Tree state: `REVIEW_REASONING_EFFORT`
  back on `XHIGH`, `VALIDATION*\*` on the prod pins, the four hacks still in place, no PR 75215 report in the DB.
