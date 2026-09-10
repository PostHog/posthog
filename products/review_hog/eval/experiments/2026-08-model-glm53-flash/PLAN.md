# PLAN — GLM 5.3 Flash as ReviewHog reviewer and validator

**Question:** how does `zai-org/glm-5.3-flash` (Baseten-served, claude adapter, effort `max`) perform as
(a) the reviewer with the current validator, and (b) the validator with the current reviewer?
Same frozen PR and harness as the Sol validator experiment (`../2026-08-validator-model-sol/`), so its
known-issue registry, judge verdicts, and the L1/L2 runs are the ground truth and control here.

## Decisions (grilled 2026-08-31)

1. **Credentials:** prod Baseten key (from the gateway's production secret store) +
   `https://inference.baseten.co/v1`, added to the repo root `.env` as `LLM_GATEWAY_BASETEN_API_*`.
2. **Gateway config:** local-only, uncommitted, reverted after the runs — `zai-org/glm-5.3-flash`
   added to `background_agents.allowed_models` and `background_agents` added to its
   `RESTRICTED_MODEL_PRODUCTS` entry (ReviewHog sandboxes route via `background_agents`; the
   sol-arm-incident trap). If GLM wins, a durable PR follows separately.
3. **Run plan:** 4 runs, serial, alternating — R1, V1, R2, V2.
   - **R arm (reviewer):** `claude / zai-org/glm-5.3-flash / max`, validator = prod pins
     (Opus 5 @ xhigh). The blind-spot sweep rides the reviewer arm, so it is GLM too.
   - **V arm (validator):** reviewer = prod pins (Sol @ xhigh / full-access), validator
     `claude / zai-org/glm-5.3-flash / max`.
   - No publish, team 1 / user 1, delete only the PR 75215 report between runs.
   - **Controls:** the existing L1/L2 runs (Sol xhigh reviewer + Opus 5 xhigh validator,
     2026-08-26). No fresh control runs.
4. **Codex retry patch: back in.** The upstream agent still gives up ~13 s into a tunnel outage
   (only the idle-timeout fix landed), so the V arm re-applies the local image patch
   (`stream_max_retries=10` / `request_max_retries=10`) that gave zero turn failures in 8 runs,
   adapted to agent 2.4.114.
5. **MCP surface: classic tools forced for all runs** (`x-posthog-mcp-mode: tools` in the sandbox
   MCP headers, local-only). GLM 5.3 Flash cannot bridge the prompts' `skill-get(...)`
   instruction to the server's default single-`exec` surface and would review without its skill.
   See FINDINGS.md item 5 for the comparability caveat this puts on the results.

## Environment facts (verified 2026-08-31)

- PR 75215 open, head frozen at `a7fb363b` (branch `stamphog-inbox-prs-experiment-frozen`).
- `zai-org/glm-5.3-flash` registered on both sides of the claude adapter (tasks registry +
  agent `models.ts`), efforts `high`/`max`; Baseten-exclusive in the gateway (no Cloudflare/Modal
  fallback); gateway pricing registered ($0.15/M in, $0.50/M out, $0.03/M cache read).
- #88893 (Codex effort fix) merged and in the released agent (npm 2.4.114 ≥ fix), so the Sol
  reviewer arm runs at true xhigh without Dockerfile effort hacks. The codex retry-count hack did
  NOT land upstream (only a sandbox `stream_idle_timeout_ms`), so tunnel-blip resilience for the
  Sol arm is still an open harness item.
- Master's sandbox checkout fetches `pull/N/head` explicitly (`git fetch origin -- <ref>` +
  `checkout -B ... FETCH_HEAD`) — resolves fine, no checkout fix needed.
- Direct gateway call to `zai-org/glm-5.3-flash` via `/review_hog/v1/messages`: HTTP 200 in 0.9 s,
  Baseten answered with a thinking block (`glm_smoke_direct.json` in the session scratchpad).

## Harness (uncommitted, revert after — re-derived from the Sol experiment's PLAN)

- `tools/github_meta.py::fetch_pr_comments` → `return []` (zero-comment clean room).
- `temporal/activities.py::split_chunks_activity` → load the pinned chunks when present
  (same `pinned_chunks.json` as `../2026-08-validator-model-sol/`).
- `reviewer/constants.py`: per-arm `REVIEW_*` / `VALIDATION_*` flips; `MAX_CONCURRENT_SANDBOXES`
  10 → 4 (comparability with the L/M/N/P runs).

## Run log

### R1 — GLM reviewer (2026-08-31 21:45–22:53 UTC)

- Arm: reviewer CLAUDE / zai-org/glm-5.3-flash / max; validator CLAUDE / claude-opus-5 / xhigh.
- Report `01a059c8-fa12-7938-9525-e19fc3d51184`, wall 4105 s (review stage 44m13s), chunks 4, units 7.
- Funnel: raw 22 → dedup 14 → **valid 0**. Opus dismissed every finding with substantive rationales (wrong line ranges, duplicate-of-existing-safeguard, self-contradicting proposals) — genuine rejection, not a pipeline error.
- Effort guard PASS (Kafka): all GLM stages `zai-org/GLM-5.3-Flash` @ `max` (9 issues-review units + 4 blind-spots); validation `claude-opus-5` @ `xhigh` ×3 chunks; dedup + selector = Sonnet internals.
- Cost: GLM review side ≈ $1.81 (497 calls-equivalent rows, ~29.6M input tokens); Opus validation ≈ $7.09; total ≈ $8.97.
- Artefacts: `runs/R1-glm-reviewer.{md,log,ai_usage.json,start,end}`.

### V1 — GLM validator (2026-08-31 23:36 – 2026-09-01 00:30 UTC)

- Arm: reviewer CODEX / gpt-5.6-sol / xhigh / full-access; validator CLAUDE / zai-org/glm-5.3-flash / max.
- Report `01a05a0a-1c37-7df5-ba1b-8139f40a83d0`, wall 3264 s (review stage 19m19s), chunks 4, units 12.
- Funnel: raw 25 → dedup 21 → **valid 15** (GLM kept 71% — R1's Opus kept 0/14 of GLM findings; L1/L2 comparison comes at scoring).
- Effort guard PASS (Kafka): all Sol review stages `gpt-5.6-sol` @ `xhigh` (8 issues-review units + 4 blind-spots); validation `zai-org/GLM-5.3-Flash` @ `max` ×4 chunks.
- Cost: Sol review ≈ $26.80; GLM validation ≈ **$1.04** over 328 calls (Opus in R1: $7.09 over 75 calls — ~7× cheaper, ~4× chattier); total ≈ $28.07.
- Artefacts: `runs/V1-glm-validator.{md,log,ai_usage.json,start,end}`.

### R2 — GLM reviewer, replicate (2026-09-01 00:33–01:23 UTC)

- Arm: reviewer CLAUDE / zai-org/glm-5.3-flash / max; validator CLAUDE / claude-opus-5 / xhigh.
- Report `01a05a3e-5d07-76b9-8394-3e289f5d3026`, wall 2982 s (review stage 40m33s), chunks 4, units 6.
- Funnel: raw 18 → dedup 12 → **valid 0**. Replicates R1: Opus dismissed all 12, again with substantive refutations (checked: provenance-is-persisted, flag-derivation, path-cannot-emit counterexamples).
- Effort guard PASS (Kafka): all GLM stages @ `max`; validation `claude-opus-5` @ `xhigh` on chunks c1/c3/c4 (no dedup'd findings landed in c2).
- Cost: GLM review side ≈ $1.62; Opus validation ≈ $6.59; total ≈ $8.27.
- Artefacts: `runs/R2-glm-reviewer.{md,log,ai_usage.json,start,end}`.

### V2 — GLM validator, replicate (2026-09-01 01:25–02:05 UTC)

- Arm: reviewer CODEX / gpt-5.6-sol / xhigh / full-access; validator CLAUDE / zai-org/glm-5.3-flash / max.
- Report `01a05a6d-ea01-7572-a284-307d709d9352`, wall 2411 s (review stage 26m48s), chunks 4, units 12.
- Funnel: raw 29 → dedup 22 → **valid 7** (much stricter than V1's 15 — high run-to-run variance in GLM's keep rate).
- Effort guard PASS (Kafka): Sol review all `xhigh`; validation `zai-org/GLM-5.3-Flash` @ `max` ×4 chunks.
- Anomaly: validation-c2 shows two zero-token `claude-opus-4-8` rows next to 2 real GLM calls — failed no-op calls; every verdict-producing call was GLM.
- Cost: Sol review ≈ $24.61; GLM validation ≈ $0.44 (157 calls); total ≈ $25.32.
- Artefacts: `runs/V2-glm-validator.{md,log,ai_usage.json,start,end}`.

### Scoring + wrap (2026-09-01 02:10–03:15 UTC)

- Scored via three Workflow fan-outs (68 agents total, 0 errors): extract → cluster match → verdict reuse / refutation-first fresh verify against worktree `1341596e` → scorecards at `findings/{RA,RB,VA,VB}.score.md`.
- Headline: GLM reviewer 7%/33% real, 0 findings survived Opus either run; GLM validator $0.02–0.05/verdict but recall 43–69%, junk filtering 25%/88% (unstable), and V2 left 12/22 findings with **no verdict at all** (validation-c2 session death). Full analysis + the ⚠️ tools-mode caveat: `FINAL_REPORT.md`.
- Optional blind argumentation judge skipped: the V2 coverage hole dominates any write-up-quality signal.
- Harness reverted to prod state (all `EXPERIMENT` marks gone); MCP scopes stay at master's `llm_skill:read` + `user:read`. A `project:read` addition was tried then dropped — the refusal hypothesis was disproven and the scope exposes the team's unmasked `secret_api_token` to an injectable session (see FINDINGS item 4). Report row deleted; DB clean. `.env` Baseten creds and this experiment folder kept.
