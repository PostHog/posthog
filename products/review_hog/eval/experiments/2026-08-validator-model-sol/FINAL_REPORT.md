# FINAL REPORT — GPT-5.6 Sol as the ReviewHog validator

**Question:** can `gpt-5.6-sol` (Codex, multi-turn) replace Claude Opus as the validation model, at lower cost and
time, without losing verdict quality? Same frozen PR (#75215 @ `a7fb363`, tree == `1341596e`), same pinned chunks and
zero-comment clean room as the reviewer-model experiment (`../2026-07-reviewer-model-glm52/`); Sol reviewer in every
run. Decisions and run log: [PLAN.md](./PLAN.md).

**Short answer (updated 2026-08-26, after four runs at real `xhigh`):** with the effort fix in the sandbox image,
Codex finally reasons at the pinned effort, and two things change. The **reviewer** gets much better: Sol at `xhigh`
surfaces 19–23 findings per run of which 50–65% are real (10 at low, 40%), finds 8 real issues none of the 18 earlier
reviews in the registry had reported (one `must_fix`), and costs ~$26 per run instead of ~$6. The **validator** does not:
Sol at `xhigh` keeps 18 of 19–20 findings, including every weak claim it kept at low, so 33–39% of what it publishes
is not real; Opus 5 at `xhigh` keeps 11–12 of 22–23 with 67–82% of them real and drops 64–82% of the not-real ones,
at ~$1.06 per verdict versus Sol's ~$0.76. Sonnet 5 at `xhigh` (two follow-up runs) behaves like Sol: keeps
16/22 then 22/22, 50% of what it keeps is real, at ~$0.50 per verdict. Sol at `medium` as the reviewer (two
afternoon runs with the Opus validator) lands in between: 14–15 findings, 7 real per run (47–50%), nothing the
registry did not already have, ~$10.50 per review and a 12–14 min review stage; Opus kept 6/14 and 7/15 with every
kept finding real. Keep Opus as the validator. The Sol-at-`xhigh` reviewer is worth shipping
once the effort fix (#88893) is in the sandbox image, with the cost increase priced in. Details in
[Runs at real xhigh](#runs-at-real-xhigh-2026-08-26).

## What happened

|                             | Opus 4.8 (I1 / I2, July) | Sol K1 (wrong tree) | Sol K2 (PR tree, pin `xhigh`) | Sol K3 (PR tree, pin `max`) |
| --------------------------- | ------------------------ | ------------------- | ----------------------------- | --------------------------- |
| Effort the model received   | xhigh                    | **low**             | **low**                       | **low**                     |
| Findings judged             | 11 / 13                  | 14                  | 10                            | 7                           |
| Kept                        | 2 / 4                    | 5                   | 8                             | 6                           |
| Kept that were real         | 2/2 / 4/4 (100%)         | 5/5 (100%)          | **4/8 (50%)**                 | **3/6 (50%)**               |
| Real findings kept (recall) | 2/4 / 4/4 (75% pooled)   | 5/9 (56%)           | **4/4 (100%)**                | **3/3 (100%)**              |
| Not-real findings dropped   | 7/7 / 9/9 (100%)         | 5/5 (100%)          | **2/6 (33%)**                 | **1/4 (25%)**               |
| Validation stage wall time  | 23m28s / 22m35s          | 4m58s               | 18m56s¹                       | 14m15s²                     |
| Validation LLM calls        | —                        | 79                  | 67                            | 37                          |
| Validation cost (gateway)   | $9.28 / $12.84           | $3.39               | $2.53                         | $1.44                       |
| Cost per verdict            | $0.84 / $0.99            | $0.24               | $0.25                         | $0.21                       |

¹ One session took 1144 s because its sandbox reported "Repository clone failed; created empty workspace" and Codex
rebuilt the tree itself; without it the stage is ~4.5 min.
² One session took 849 s because local Modal sandbox provisioning took 12 minutes before the agent started; the three
sessions judged in 155–200 s each, 30–70 s per verdict.

Sol costs come from the gateway's own `$ai_generation` events (read from the local Kafka topic
`events_plugin_ingestion_ai` with `scripts/kafka_ai_usage.py`, because local ingestion is down), at the gateway's
LiteLLM rates ($4 / $20 per M in / out, $0.40 cache read). Opus costs are the cache-aware list-price figures from the
July dumps, built from the same events. Earlier versions of this report quoted $0.72–0.93 for Sol validation from the
agent logs (a `usage_from_logs.py` script, since removed); that method counts only the last LLM call of each turn and undercounted
3–4×. Sol is ~4–5× cheaper per verdict than Opus, not ~12×. Selection and dedup one-shots (Sonnet, ≤ $0.15) are not
counted on either side.

### Runs 2 and 3: verdict quality (the runs that count)

_Ground truth:_ each finding was matched to the 76 known issues of this PR (`known_clusters.json`, built from the
July judge files). Findings in unanimous clusters take the cluster's verdict; findings in mixed clusters were
verified one by one, refutation-first, against the frozen worktree (`findings/verify/`), and later runs reuse those
verdicts when the claim is identical. Opus's numbers use the July per-finding verdicts.

|          | K2 kept | K2 dropped | K3 kept | K3 dropped |
| -------- | ------- | ---------- | ------- | ---------- |
| real     | 4       | 0          | 3       | 0          |
| not real | 4       | 2          | 3       | 1          |

- **Every real finding was kept in both runs**: the receiver-leg provenance hole (KB6 / KC6, must_fix), the
  single-acting-reviewer toggle (KB8 / KC7, should_fix) and the stale "draft on purpose" text (KB2 / KC5, consider).
  K2 also kept the `internal=True` receiver guard (KB7, should_fix); the reviewer did not surface it in K3.
- **Half of what it kept is not real, both times, and it is the same three claims.** The unscoped `find_task_run`
  lookup (KB1 / KC2 — the lookup is already repo-scoped and the other-team → None contract is tested; Sol labelled it
  `must_fix` both times) and the broker/retry hardening ask, reported as two findings each run (KB3+KB4 / KC3+KC4 —
  copies the existing webhook path's deliberate design and is covered by later re-fires). K2 also kept the
  queue-time toggle trust (KB10, refuted six times in July). Opus dropped all 16 not-real findings it saw in July.
- The drops were right: KB5 (doc-wording nit), KB9 (a GitHub call before dedupe, refuted in July), KC1 (a JSON-boolean
  coercion nit, refuted seven times in July).
- Sol read the validation-criteria skill (MCP works since #88697) and still kept "defensive hardening" items the skill
  says to drop. A blind judge of the write-ups (`findings/argumentation_judge_K3_vs_K2.json`) found K3 and K2 the same
  length (101 words median) and K2 slightly better argued on 5 of 6 paired findings. No sign of more reasoning at
  `max`, which fits the effort finding below.

Ground truth per finding: `findings/KB.truth.json`, `findings/KC.truth.json`; matches: `findings/K{B,C}.match.json`;
scores: `findings/K{B,C}.score.md`.

### Run 1 was judged on the wrong tree

Run 1's validator dismissed findings by citing code that exists only on master (`facade/api.py:694-747`,
`test_webhooks.py:2000-2061`), and the sandbox's own `git rev-parse HEAD origin/master` returned master's tip.
Root cause: since 2026-07-15 ReviewHog passed `pull/N/head` as the sandbox branch and the Tasks checkout, which
resolves only `refs/heads/<name>`, fell back to a fresh branch on master. Every prod review sandbox since then
investigated master instead of the PR (the reviewer still got the diff in its prompt, so review volume never
dropped). Fixed in #88775. Run 1 stays here as the before/after data point; its numbers describe Sol judging the
wrong tree and still keeping only real findings.

## The effort pin never reached Codex

**Evidence.** The gateway records `$ai_effort` from each request's `reasoning.effort`. Every `gpt-5.6-sol` call in
K1, K2 and K3 carries `low` (79 / 67 / 37 validation calls, and all review and blind-spot calls), with 60–110
reasoning tokens per call; the Sonnet one-shots in the same runs carry `xhigh`. On the sandbox side everything said
`max` in K3: `TaskRun.state.reasoning_effort`, the `POSTHOG_CODE_REASONING_EFFORT` env, and the Codex session's own
config option (`effort = max` in the `session/new` result). The gateway buffer holds no Codex request with any effort
other than `low`.

**Prod.** Project 2, `ai_product = background_agents` (the gateway product every Tasks sandbox uses), last 3 days:
Opus validation `xhigh` 14,582 calls; `gpt-5.6-sol` review 13,649 and blind-spot 5,247 calls, all `low`, 112 reasoning
tokens per call on average. Over 21 days, since at least 2026-08-04, 100% of `gpt-5.6-sol` calls were `low` every
day. So the Sol arm of the prod 50/50 A/B (live since 2026-08-03) and every Sol experiment (the July 7-way reviewer
experiment, K1–K3) ran at Codex's low effort.

**Mechanism.** The Codex adapter in `@posthog/agent` (2.4.86 in the sandbox image, bundling `@openai/codex` 0.144.0)
sends two things on every `turn/start`: an `effort` param and a `collaborationMode` object built by
`collaborationModeForTurn()` in `products/desktop/packages/agent/src/adapters/codex-app-server/session-config.ts`,
whose settings hold only `{ model }`. Codex takes a provided collaboration mode as is and applies the separate
`effort` only when no collaboration mode is sent (`codex-rs/core/src/codex_thread.rs`, the
`preview_thread_settings_overrides` path, at `rust-v0.144.0`). The provided mode has no `reasoning_effort`, so each turn
falls back to the model's default in Codex's bundled catalog (`codex-rs/models-manager/models.json`): `low` for
`gpt-5.6-sol`, `medium` for `gpt-5.6-terra` and `gpt-5.6-luna`. The Claude adapter passes the effort through session
meta and is unaffected, which is why Opus shows `xhigh`.

**Fix.** PR #88893. One line in the agent: include `reasoning_effort: this._effort` in `collaborationModeForTurn().settings`
(or send no `collaborationMode` when only the mode is unchanged). A config-level `-c model_reasoning_effort` would not
help: Codex replaces it with the collaboration mode's effort on every turn (`build_per_turn_config` in
`turn_context.rs`). Verify after the agent release lands in the sandbox image by checking `$ai_effort` on the first
Codex call of a run. **Verified locally on 2026-08-26:** with the one-line patch applied to the installed agent in the
local sandbox image, a 3-turn Codex smoke pinned at `xhigh` produced 12 gateway calls, all with `$ai_effort=xhigh`
(`runs/fix-smoke.gateway_events.json`).

## Runs at real xhigh (2026-08-26)

Four runs on the same frozen PR, same pinned chunks, same zero-comment clean room, with the sandbox image patched so
Codex receives the pinned effort (`$ai_effort=xhigh` confirmed on the first review calls and the first validation
calls of every run). Reviewer = Sol at `xhigh` in all four. Arm L = Opus 5 validator at `xhigh` (the prod pins).
Arm M = Sol validator at `xhigh` / `full-access`. Order L1, M1, L2, M2. Arm N (Alex's follow-up the same
morning) = Sonnet 5 validator at `xhigh`, runs N1, N2. Arm P (the afternoon) = Sol **reviewer** at `medium` with
the Opus 5 validator, runs P1, P2. Ground truth as before: 76 known clusters,
per-claim refutation-first verification against the frozen worktree for mixed clusters and new claims
(`findings/verify/`, 32 fresh verdicts today), identical claims reuse a verdict. Full table:
`findings/xhigh_summary.md`; per-run scores `findings/{LA,LB,MA,MB,NA,NB,PA,PB}.score.md`.

|                             | L1 (Opus 5) | L2 (Opus 5) | M1 (Sol)     | M2 (Sol)      | N1 (Sonnet 5) | N2 (Sonnet 5) |
| --------------------------- | ----------- | ----------- | ------------ | ------------- | ------------- | ------------- |
| Findings judged             | 23          | 22          | 19           | 20            | 22            | 22            |
| Kept                        | 11          | 12          | **18**       | **18**        | 16            | **22**        |
| Kept that were real         | 9/11 (82%)  | 8/12 (67%)  | 11/18 (61%)  | 12/18 (67%)   | 8/16 (50%)    | 11/22 (50%)   |
| Real findings kept (recall) | 9/12 (75%)  | 8/11 (73%)  | 11/12 (92%)  | 12/13 (92%)   | 8/11 (73%)    | 11/11 (100%)  |
| Not-real findings dropped   | 9/11 (82%)  | 7/11 (64%)  | **0/7 (0%)** | **1/7 (14%)** | 3/11 (27%)    | **0/11 (0%)** |
| Validation wall time        | 30 min      | 26 min      | 13 min       | 16 min        | 22 min        | 26 min        |
| Validation LLM calls        | 260¹        | 176         | 173          | 161           | 185²          | 206²          |
| Validation cost (gateway)   | $24.35      | $23.42      | $13.62       | $15.97        | $10.53        | $11.72        |
| Cost per verdict            | $1.06       | $1.06       | $0.72        | $0.80         | $0.48         | $0.53         |

¹ 134 Opus calls plus 126 Sonnet calls the Claude session made itself (sub-agents), $3.60 of the total.
² Includes 6 / 9 `claude-opus-4-8` sub-agent calls the Sonnet session made ($1.22 / $2.37).

### The validator: Sol at xhigh keeps everything

- Sol dropped one finding per run and kept the other 18. The seven not-real findings it kept in each run include
  every member of the three families it kept at low: the unscoped `find_task_run` lookup (cluster 39: MA12, MB18),
  the broker/retry hardening asks (cluster 58: MA4, MA14, MA15, MB3, MB9, MB10, all six kept), and the queue-time
  toggle (cluster 31: MA18, MB1). More reasoning did not move its bar; the write-ups got shorter (median 126 words vs
  335 for Opus) and, per the blind judge (`findings/argumentation_judge_L_vs_M.json`), mostly restate the finding
  instead of testing it — Opus won 21 of 29 paired write-ups on evidence and verification, Sol won 5.
- The one finding Sol dropped each run was the same real one: the webhook-site copy of the secondary-reviewer toggle
  (MA5, MB11, `should_fix`), while it kept the receiver-site copy of the same claim (MA11, MB19). Its verdicts are not
  consistent with themselves inside a run.
- Opus 5 at `xhigh` dropped 16 of 22 not-real findings across the two runs and kept 17 of 23 real ones. Its misses:
  it kept the unscoped-lookup claim once (LA16) and one broker variant once (LB5), and it dropped six real findings
  (LA8, LA17, LA21, LB10, LB13, LB17 — one `must_fix`, three `should_fix`, two `consider`). Two of those it judged
  the other way in the other run (the toggle claim dropped as LA17 in L1 was kept as LB11 in L2; the engine-flag
  claim dropped as LB10 in L2 was kept as LA19 in L1), so some of that is run-to-run noise on a 22-finding sample.
- Cost: Opus $1.06 per verdict, Sol $0.72–0.80. The 4–5× gap seen at low is gone: at `xhigh` Sol spends 40–44k
  reasoning tokens per validation stage and its cost per verdict is ~70% of Opus's, for a validator that removes
  almost nothing.

### Sonnet 5 as validator: Sol's bar at a lower price

- Sonnet 5 at `xhigh` kept 16 of 22 in N1 and all 22 in N2. Kept-real 50% both times; not-real dropped 3/11 then
  0/11. It kept the same families Sol keeps (broker/retry: NA4, NA6, NA16, NB4, NB5, NB15, NB16; unscoped lookup:
  NA18, NB12; queue-time toggle: NA9, NA21, NB22) plus this morning's new refuted claims (NB1, NB7, NB13, NB19).
- What it dropped in N1 was mostly real: the any-bot carve-out (NA5, `must_fix`), the engine-flag binding (NA22,
  `must_fix`) and the receivers-side toggle claim (NA13, `should_fix`), against three not-real drops (NA3, NA8,
  NA12). In N2 it dropped nothing.
- Cheapest per verdict ($0.48–0.53, ~half of Opus), about as fast as Opus per verdict (22–26 min for 22). The
  blind judge (`findings/argumentation_judge_N_vs_L.json`) scored its write-ups below Opus on every lens (evidence
  4 vs 5, verify 3 vs 4, readability 2 vs 3; Opus won 20 of 29 pairs, Sonnet 2): nearly as long (median 290 vs 335
  words), 33-word sentences, and it contradicts itself inside a run (NA1 vs NA8/NA13; NA5/NA22 vs NA7/NA10/NA11).
  Its sessions also spawned Opus 4.8 sub-agents (6 and 9 calls) on their own.
- Reviewer side was unchanged (11/22 real in both runs, 2 new-to-registry real issues each, all repeats of claims
  verified earlier today), as expected: the reviewer does not know which validator follows.

### The reviewer: Sol at xhigh is a different reviewer

Same PR, same chunks, same skills. Reviewer-side numbers count the deduplicated findings before the validator
(`findings/reviewer_side.md`):

| Reviewer                                       | Findings after dedup | Real                | Real clusters found | New real issues |
| ---------------------------------------------- | -------------------- | ------------------- | ------------------- | --------------- |
| Sol at low, K2 / K3 (Aug 25)                   | 10 / 7               | 4 (40%) / 3 (43%)   | 4 / 3               | 0 / 0           |
| Sol at low, I1 / I2 (July, Opus 4.8 validator) | 11 / 13              | 4 (36%) / 4 (31%)   | 4 / 4               | 0 / 0           |
| **Sol at xhigh, L1 / L2**                      | 23 / 22              | 12 (52%) / 11 (50%) | 9 / 4               | 2 / 5           |
| **Sol at xhigh, M1 / M2**                      | 19 / 20              | 12 (63%) / 13 (65%) | 6 / 5               | 1 / 4           |
| **Sol at medium, P1 / P2**                     | 14 / 15              | 7 (50%) / 7 (47%)   | 6 / 3               | 0 / 0¹          |

¹ PB5 has no registry cluster but is the opt-out supersede race LB20 found at `xhigh` this morning, so it is not new.

- Three times the real findings per run (11–13 vs 3–4), at a better real rate (50–65% vs 31–43%).
- Eight real issues that none of the 18 earlier reviews in the registry had reported, all verified against the
  frozen tree tonight: the webhook facade authorizes on caller-writable task attribution (LA15 = MA9 = MB17, **must_fix**,
  distinct from the receiver-leg provenance hole); hosted WAIT outcomes never reach the self-driving dashboard
  (LB17, `should_fix`); the hosted bot predicate omits `posthog-bot` and wastes a sandbox plus a public refusal
  comment on its PRs (LB22, `should_fix`); and five `consider`-grade dedupe/opt-out gaps (LA8 = MB13, LB2, LB20,
  LB21 = MB12, MB5). They are not yet folded into `known_clusters.json`, which stays the July registry.
- The reviewer's own priorities are inflated: it labels most real `should_fix`/`consider` issues `must_fix`. The
  validator's priority override matters more at `xhigh`, not less.
- Price: review + blind-spot stages cost $26 per run at `xhigh` (368–373 gateway calls, 75–85k reasoning tokens)
  against $5.60–6.60 at low (102–113 calls). Wall time for the review stage was 26–34 min at concurrency 4 (see the
  harness note below) against 3.5 min at low with concurrency 10.

### Sol at medium as reviewer: half of xhigh for 40% of the price, nothing new

Two runs the same afternoon with only `REVIEW_REASONING_EFFORT` changed (`$ai_effort=medium` on every reviewer call,
validator on the prod Opus pins). Scores `findings/{PA,PB}.score.md`, reviewer side `findings/reviewer_side.md`.

- Reviewer: 7 real findings per run (low 3–4, `xhigh` 11–13) at a 47–50% real rate (low 31–43%, `xhigh` 50–65%).
  It reports the clusters low reports (the receiver-leg provenance hole, the secondary-reviewer toggle, the draft
  claim in the trusted prompt) and adds, in P1, the any-bot carve-out (75), the stale approval on resolver failure
  (29) and the engine-flag binding (6); P2 added the opt-out supersede race (LB20). Nothing that the registry or the
  morning's `xhigh` runs had not already reported, and no LA15 (the `must_fix` webhook-facade authorization hole)
  in either run. The not-real half is the same families every effort level produces: broker/retry hardening asks
  (cluster 58, three per run), the unscoped `find_task_run` lookup (39), the queue-time toggle (31), plus one
  doc-form restatement (PA7) and one deferred-import claim (PB14, verified not real: the facade package is already
  loaded at `django.setup()`).
- Price and time: review + blind-spot $10.23 / $10.76 (165–171 gateway calls, 37–40k reasoning tokens) against
  $5.60–6.60 at low and ~$26 at `xhigh`; review stage 12.5 / 14 min at concurrency 4 (`xhigh` 26–34 min, low 3.5 min
  at concurrency 10). Whole run 33 / 43 min.
- Opus 5 validator on the medium sets was flawless on precision: every kept finding real in both runs, 15/15 not-real
  dropped, one real miss (PA12, the secondary-reviewer toggle, `should_fix` — the same claim it dropped as LA17 in L1
  and kept in L2 and P2). Part of that is the input: 14–15 findings whose not-real half is the well-known families.

| Opus 5 validator            | L1 (xhigh reviewer) | L2 (xhigh reviewer) | P1 (medium reviewer) | P2 (medium reviewer) |
| --------------------------- | ------------------- | ------------------- | -------------------- | -------------------- |
| Findings judged             | 23                  | 22                  | 14                   | 15                   |
| Kept                        | 11                  | 12                  | 6                    | 7                    |
| Kept that were real         | 9/11 (82%)          | 8/12 (67%)          | 6/6 (100%)           | 7/7 (100%)           |
| Real findings kept (recall) | 9/12 (75%)          | 8/11 (73%)          | 6/7 (86%)            | 7/7 (100%)           |
| Not-real findings dropped   | 9/11 (82%)          | 7/11 (64%)          | 7/7 (100%)           | 8/8 (100%)           |
| Validation wall time        | 30 min              | 26 min              | 17 min               | 27 min               |
| Validation cost (gateway)   | $24.35              | $23.42              | $15.80               | $13.90¹              |
| Cost per verdict            | $1.06               | $1.06               | $1.13                | $0.93                |

¹ Includes 2 `claude-opus-4-8` sub-agent calls the Opus session made ($1.06).

Read across the three effort levels, the reviewer's real-finding count roughly doubles per step (3–4 → 7 → 11–13) and
so does the price ($6 → $10.50 → $26), but the new-issue discovery that made `xhigh` interesting (8 issues no earlier
review had) did not appear at `medium` in two runs. If the `xhigh` price is the blocker, `medium` is the fallback that
still beats today's prod reviewer; it is not a substitute for `xhigh` on discovery.

### What it took to run at xhigh (harness only, not shipped)

Every review wave at `xhigh` died twice before the first run completed: all 8 sandboxes lost their first big Codex
request at the same instant, ~60 s after the agents started, with `stream disconnected before completion: error
sending request` on the gateway tunnel and `fetch failed` on the django tunnel. The ngrok inspector shows no sandbox
traffic reaching this machine for ~85 s each time, while a probe minutes later reaches all three tunnels in <1 s.
Codex's retry backoff is 200 ms × 2ⁿ, so its default 5 stream retries give up in ~13 s. This is K3's "bug 6"
(4/9 units then) made total by eight concurrent long first-requests. Two local hacks got the runs through:
`stream_max_retries=10` / `request_max_retries=10` (~200 s of backoff) and a 300 s stream idle timeout patched into
the installed agent in the sandbox image, and `MAX_CONCURRENT_SANDBOXES` 10 → 4. After that, zero turn failures in
four runs. Run log and the two self-inflicted stalls (skills-cache rebuild restarting the worker, a `.py` written
under `products/` during a run): [PLAN.md](./PLAN.md).

## Bugs found on the way

1. **ReviewHog sandboxes had no MCP since 2026-08-13** (#88697, merged). `REVIEW_MCP_SCOPES` lacked `user:read`, which
   the MCP server needs to open a session; every reviewer/validator/resolver session was refused and ran without its
   skill. Prod `$mcp_auth_failed` for sandbox agents: 0 before Aug 13, hundreds–thousands a day after.
2. **Review sandboxes checked out master, not the PR, since 2026-07-15** (#88775, in review). See above.
3. **Local sandbox image build broken by #88274** (#88698, merged): the DEBUG Modal build context lacked
   `products/desktop/packages/agent-shadow/`.
4. **Runner proceeds without a repository.** One validation sandbox logged "Repository clone failed; created empty
   workspace" and the agent carried on. Not fixed; worth a fail-fast in the Tasks runner.
5. **Codex sandboxes ignore the pinned reasoning effort** (this report, not yet fixed). Affects every Codex Tasks
   sandbox, not only ReviewHog.
6. **Codex turn stalls pin a sandbox for 30 minutes.** In K3, four of nine review sandboxes ended their turn with
   `stopReason=refusal` inside one 5-second window and could not report completion ("fetch failed"); the worker waited
   the full 1800 s poll timeout before retrying, and all four retries succeeded in ~3 minutes. A shared gateway or
   tunnel blip, not the prompt; the cost is wall time only.

7. **Codex gives up on a tunnel blip in ~13 s.** Codex's provider config in the agent (`spawn.ts`) sets only
   `stream_idle_timeout_ms`; the retry counts stay at Codex's defaults with 200 ms × 2ⁿ backoff. An ~85 s outage on
   the gateway path kills every in-flight turn, and the poll then waits 30 min before retrying. Ten retries survived
   it tonight (local hack); the agent should set `stream_max_retries` / `request_max_retries` for sandbox runs and
   the agent-server should retry its completion signal. Prod sandboxes go through no ngrok, so the exposure there is
   the gateway itself, not this tunnel.
8. **Local Modal image builds restart the dev worker mid-build.** `LocalSkillsCache.ensure_built()` rewrites
   `products/posthog_ai/dist/skills/**/*.py` inside `create_sandbox_for_repository`, and the dev worker's nodemon
   watches `products/**/*.py`, so the worker is SIGTERMed while it builds the image (~70 restarts, then `spawn
EBADF`). Dev only. Exclude `products/posthog_ai/dist` from the nodemon watch, or build the skills outside the
   worker.
9. **Opus validation sessions fan out to Sonnet.** L1's validation stage made 126 `claude-sonnet-5` calls next to
   134 Opus calls (the Claude session's own sub-agents), $3.60 of $24.35, all tagged `validation-*`. Harmless, but
   any per-model cost split of the validator has to include them.

## What we learned about Codex as a multi-turn validator

- The multi-turn session works end to end (smoke test: 3 turns, context kept, `skill-get` on a follow-up turn;
  real runs: 3–4 concurrent sessions, 7–14 turns, no empty-turn retries).
- Sol at low effort is fast: 30–70 s per verdict once the session is warm; Opus at xhigh took ~2 min.
- Sol keeps more. On the correct tree it kept 8 of 10 and 6 of 7; Opus kept 2 of 11 and 4 of 13 on the same PR. The
  extra keeps are the same weak claims each run, so this is a stable bar, not run noise.
- Sol investigates hard, sometimes too hard: on the wrong tree it reasoned from `git log --all` and master; with no
  tree at all it fetched the PR ref itself. Useful instinct, but the verdict is only as good as the tree it is given.
- Everything above describes Sol at `low`. What Sol does at `xhigh` is still unmeasured.

## Recommendation

1. **Keep Opus as the validator.** At real `xhigh` Sol still keeps 18 of 19–20 findings, drops almost none of the
   not-real ones (0/7 and 1/7), and the cost advantage shrinks to ~30% per verdict. Sonnet 5 at `xhigh` is the same
   story at half the price (kept 16/22 and 22/22, 50% real), so the cheaper Claude tier is not a way out either. The stricter refutation-first
   prompt is the only thing left to try for Sol as a validator; nothing in these four runs suggests more effort
   alone will change its bar.
2. **Ship the effort fix and run the Sol reviewer at `xhigh`.** #88893 needs review and an agent release into the
   sandbox image. Once it lands, every Codex sandbox — the ReviewHog reviewer and blind-spot check, and every other
   Codex Tasks run — moves from `low` to its pinned effort. For ReviewHog that is 3× the real findings per run and 8
   new real issues on a PR already reviewed 18 times, at ~$26 instead of ~$6 per review and a review stage that takes
   25–35 min at concurrency 4 (measure it at 10 in prod). Price that in before flipping. If that price is the
   blocker, `medium` is the fallback: 7 real findings per run (double low, half `xhigh`) at ~$10.50 and a 12–14 min
   review stage, with Opus validation flawless on those sets — but it found nothing new in two runs.
3. **Before the agent release, harden Codex's turn against gateway blips** (bug 7): set the retry counts in the
   agent's codex provider config and retry the completion signal. Without it the first `xhigh` waves in prod can
   die the way they did here whenever the gateway path stutters for more than ~15 s.
4. **Re-read the prod 50/50 A/B as "Sol at low".** Its Sol arm never ran at `xhigh`; the comparison starts over
   after the fix.
5. **Revert the experiment hacks on this tree** when done: the two `sed` lines in `Dockerfile.sandbox-base`,
   `return []` in `fetch_pr_comments`, the chunk pin in `split_chunks_activity`, and `MAX_CONCURRENT_SANDBOXES = 4`.
   `VALIDATION_*` is already back on the prod pins.
