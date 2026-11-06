# PLAN — Kimi K3 as ReviewHog reviewer and validator

**Question:** how does `moonshotai/kimi-k3` (Modal-served, claude adapter, effort `max`) perform as
(a) the reviewer with the current validator, and (b) the validator with the current reviewer?
Same frozen PR and harness as the GLM 5.3 Flash experiment (`../2026-08-model-glm53-flash/`) and the
Sol validator experiment (`../2026-08-validator-model-sol/`), so their known-issue registry, judge
verdicts, and the L1/L2 control runs are the ground truth and control here.

## Decisions (grilled 2026-09-01)

1. **Identical harness to the GLM 5.3 Flash run.** Same frozen PR 75215 @ `a7fb363b` (tree
   `1341596e`), pinned 4 chunks / 22 files, comments mocked to none, team 1 / user 1, DB-only (no
   publish), local stack + ngrok, Modal sandboxes, `MAX_CONCURRENT_SANDBOXES = 4`.
2. **Effort `max`** on the Kimi arms (its ceiling; the endpoint advertises effort ∈ {low, high, max}).
3. **Run plan:** 4 runs, serial, alternating — R1, V1, R2, V2.
   - **R arm (reviewer):** `claude / moonshotai/kimi-k3 / max`, validator = prod pins (Opus 5 @ xhigh).
     The blind-spot sweep rides the reviewer arm, so it is Kimi too.
   - **V arm (validator):** reviewer = prod pins (Sol @ xhigh / full-access), validator
     `claude / moonshotai/kimi-k3 / max`.
   - **Controls:** the existing L1/L2 runs (Sol xhigh reviewer + Opus 5 xhigh validator, 2026-08-26).
     No fresh control runs.
4. **Positioning:** Kimi K3 is priced $3/M in, $15/M out, $0.30/M cache read (gateway cost bridge) —
   Sonnet/Opus-class, NOT a cheap flash model. So its results are read against the **premium pins**
   (Sol reviewer / Opus validator), not the GLM/flash cohort.
5. **Codex retry patch: back in** for the V arm's Sol reviewer — the upstream agent still gives up
   ~13 s into a tunnel outage, so the local `Dockerfile.sandbox-base` patch
   (`stream_max_retries=10` / `request_max_retries=10`) is re-applied, same as the GLM run.
6. **MCP surface:** decided by the smoke. If Kimi cannot bridge the prompts' `skill-get(...)`
   instruction to the server's default single-`exec` surface (as GLM 5.3 Flash could not), the runs
   force classic per-tool mode (`x-posthog-mcp-mode: tools`, local-only) and the final report carries
   the same comparability caveat. If Kimi bridges `skill-get` on the exec surface, no override is
   applied and there is no caveat.

## Environment facts (verified 2026-09-01)

- `moonshotai/kimi-k3` registered on the claude adapter (tasks registry `utils.py` + agent
  `models.ts`), efforts `high`/`max`; **Modal-served** in the gateway (`modal.py` pins it to the
  `modal_kimi_api_base` setting; no Cloudflare/Baseten fallback). Endpoint + Modal proxy-auth come
  from the gateway's production secret store (`LLM_GATEWAY_MODAL_KIMI_API_BASE` + Modal key/secret).
- Direct generation smoke against the Modal endpoint: `POST /v1/chat/completions` with
  `moonshotai/kimi-k3` → HTTP 200 in ~1.2 s, reasoning model (`reasoning_content`), prompt caching
  live. Model id is case-insensitive (lowercase pin the gateway sends works). The base URL **must**
  end in `/v1` (the server 404s `/models`, serves `/v1/models`).
- PR 75215 open, head frozen at `a7fb363b` (branch `stamphog-inbox-prs-experiment-frozen` @
  `1341596e`); `pinned_chunks.json` and the 76-cluster `known_clusters.json` are reused from the
  sibling experiment dirs.
- The gateway advertises `moonshotai/kimi-k3` on `background_agents` (the product ReviewHog sandboxes
  route through) after the config edit — probed `localhost:3308/background_agents/v1/models`.

## Harness (uncommitted, EXPERIMENT local-only, revert after)

- **Model registry (both repos):** `utils.py` `moonshotai/kimi-k3` efforts `()` → `(HIGH, MAX)`;
  agent `models.ts` `MODEL_EFFORT_LEVELS` + `moonshotai/kimi-k3: ["high","max"]` (or the agent-server
  hard-errors at startup).
- **Gateway allowlists:** `moonshotai/kimi-k3` added to `background_agents.allowed_models` (the
  sandbox route both arms use) and `review_hog.allowed_models` (direct-call parity). Kimi is not in
  `RESTRICTED_MODEL_PRODUCTS`, so — unlike GLM — no restricted-products edit is needed. The
  `tasks-kimi-k3` access flag is bypassed locally by the gateway's debug mode.
- **Clean room:** `tools/github_meta.py::fetch_pr_comments` → `return []` (zero-comment room);
  `temporal/activities.py::split_chunks_activity` → load the pinned chunks when present.
- **`reviewer/constants.py`:** per-arm `REVIEW_*` / `VALIDATION_*` flips; `MAX_CONCURRENT_SANDBOXES`
  10 → 4.
- **`Dockerfile.sandbox-base`:** Codex retry patch (decision 5), for the V arm.
- **Tools-mode override:** applied only if the smoke shows Kimi cannot bridge `skill-get` (decision 6).

## Smoke (2026-09-01)

- `scripts/kimi_mts_smoke.py`: 3-turn warm session pinned to `claude / moonshotai/kimi-k3 / max`,
  turn 3 mirrors the pipeline's `skill-get(review-hog-validation-criteria, version=1)` imperative on
  the **default** MCP surface to decide the tools-mode question. Triggers the cold image rebuild.
- Result: **PASS** (2026-09-01, after the dist-rebuild fix — FINDINGS 1). Turn 1 (74s) read the file
  - validated JSON; turn 2 (10s) recalled from history without tools; turn 3 (90s)
    `skill_found: true, version 1, heading "# Review validation criteria"`. **Kimi K3 bridges
    `skill-get` on the default exec surface — no tools-mode override needed, no comparability caveat**
    (unlike GLM 5.3 Flash). Decision 6 resolves to: default MCP surface, same as the 08-26 controls.

## Run log

_(to be filled as runs complete: report id, wall time, funnel raw→dedup→valid, effort-guard PASS
via Kafka, cost)_

### R1 — Kimi reviewer (2026-09-01 18:21–18:53 UTC)

- Arm: reviewer CLAUDE / moonshotai/kimi-k3 / max; validator CLAUDE / claude-opus-5 / xhigh.
- Report `01a05e34-87a1-7f15-8496-8eb028cde229`, wall ~32 min, head `a7fb363b`, pinned 4 chunks.
- Funnel: dedup **22** (9 should_fix + 13 consider) → **valid 2** (1 `security` should_fix [publishable]
  - 1 `best_practice` consider). Opus dropped 20/22. Body: "Found 1 should fix, 1 consider."
- Effort guard PASS (Kafka): all Kimi stages (9 issues-review units + 4 blind-spots) @ `max`;
  validation `claude-opus-5` @ `xhigh` ×4 chunks; dedup + selection = Sonnet 5 internals.
- Cost: Kimi review side ≈ $13.83 ($10.45 review + $3.38 blind-spot); Opus validation ≈ $13.22;
  internals $0.12; **total ≈ $27.17** (~3× GLM's R1 — Kimi is Sonnet-class; heavy prompt caching, 18M
  cache-read on review).
- Artefacts: `runs/R1-kimi-reviewer.{log,ai_usage.json,start,end}`, `findings/R1.extract.json`.

### V1 — Kimi validator (2026-09-01 18:58–19:14 UTC)

- Arm: reviewer CODEX / gpt-5.6-sol / xhigh (pinned) / full-access; validator CLAUDE / moonshotai/kimi-k3 / max.
- Report `01a05e56-b3ad-7567-bed9-741cc9404d41`, wall ~16 min, head `a7fb363b`.
- Funnel: Sol reviewer dedup **8** (2 must_fix + 6 should_fix) → Kimi validator kept **4** (is_valid), dropped 4;
  **all 8 got a verdict — no no-verdict hole** (GLM V2's disqualifier); body "Found 3 should fix, 1 consider".
- ⚠️ **Reviewer-effort caveat (FINDINGS 7): the Sol reviewer ran at `low`, not the pinned `xhigh`.** The
  local-overlay codex adapter resolved effort to low (Sol review $3.33 / 8 findings vs GLM's Sol@xhigh
  ~$26.80 / ~22 findings). This V-arm finding set is smaller/weaker than GLM's Sol@xhigh controls, so
  Kimi-validator **coverage + keep/drop behavior are valid, but precision/recall are NOT directly
  comparable** to the 08-26 validator controls (LA/LB/MA/MB/NA/NB).
- Effort guard (Kafka): validation `moonshotai/kimi-k3` @ **max** ✓ (95 calls); Sol review + blind-spot
  @ **low** ✗ (should be xhigh); dedup + selection Sonnet 5.
- Cost: Sol review ≈ $4.84 ($3.33 review + $1.51 blind-spot); Kimi validation ≈ **$2.25**; total ≈ $7.18.
- Artefacts: `runs/V1-kimi-validator.{log,ai_usage.json,start,end}`, `findings/V1.extract.json`.

### R2 — Kimi reviewer, replicate (2026-09-01 19:24–20:08 UTC)

- Arm: reviewer CLAUDE / moonshotai/kimi-k3 / max; validator CLAUDE / claude-opus-5 / xhigh.
- Report `01a05e6d-d188-7011-bd50-3ff9d222bb97`, wall ~44 min, head `a7fb363b`, pinned 4 chunks.
- Funnel: dedup **25** (3 must_fix + 10 should_fix + 12 consider) → **valid 5** (1 must_fix + 2 should_fix
  - 2 consider). Opus dropped 20/25. Body: "Found 1 must fix, 2 should fix, 2 consider." Better than
    R1's 2 kept — a **must_fix survived** this run.
- Effort guard PASS (Kafka): all Kimi stages @ `max`; validation `claude-opus-5` @ `xhigh` ×chunks;
  dedup + selection = Sonnet 5.
- Cost: Kimi review side ≈ $12.81 ($7.63 review + $5.18 blind-spot); Opus validation ≈ $21.92;
  internals $0.17; **total ≈ $34.90**.
- Note: the CLI launcher was reaped mid-run (background-task kill — not OOM, 47% mem free); the durable
  Temporal workflow finished server-side, results read from the DB.
- Artefacts: `runs/R2-kimi-reviewer.{log,ai_usage.json,start,end}`, `findings/R2.extract.json`.

### V2 — Kimi validator, replicate (2026-09-01 20:11–20:49 UTC)

- Arm: reviewer CODEX / gpt-5.6-sol / xhigh (pinned) / full-access; validator CLAUDE / moonshotai/kimi-k3 / max.
- Report `01a05e99-776b-70ec-b277-b026faa8b438`, wall ~38 min, head `a7fb363b`.
- Funnel: Sol reviewer dedup **11** (5 must_fix + 6 should_fix) → Kimi validator kept **4**, dropped 7;
  all 11 got a verdict; body "Found 1 must fix, 3 should fix".
- ⚠️ Reviewer-effort caveat (FINDINGS 7): Sol ran at `low` again (review $3.78 / 11 findings).
- ⚠️ Validator contamination (FINDINGS 9): chunk **c4's Kimi session died** (4 no-op calls, $0.00) and
  **fell back to `claude-opus-4-8`** (9 real calls, $1.79) — so **1 of 11 findings (c4) got an OPUS
  verdict, not Kimi**. Kimi genuinely validated 10/11; its "no verdict hole" on c4 was the harness
  fallback, not Kimi. V1 (all-Kimi) is the clean validator run.
- Effort guard (Kafka): validation `moonshotai/kimi-k3` @ **max** ✓ (c1/c2/c3, 143 calls); c4
  `claude-opus-4-8` @ max (fallback); Sol review + blind-spot @ **low** ✗.
- Cost: Sol review ≈ $5.60; Kimi validation ≈ $3.40; Opus c4 fallback ≈ $1.79; total ≈ $10.90.
- Artefacts: `runs/V2-kimi-validator.{log,ai_usage.json,start,end}`, `findings/V2.extract.json`.

### Scoring + wrap (2026-09-01 20:50–21:30 UTC)

- Scored all 66 post-dedup findings via one Workflow fan-out (66 agents, 0 errors, ~4.7M tokens):
  each finding matched to the 76-cluster registry (26 cluster-reuse) or refutation-first fresh-verified
  against worktree `1341596e` (40 fresh); **8 of 66 real**. Scorecards: `findings/{R1,R2,V1,V2}.score.md`;
  merged truth: `findings/scored.json`.
- Headline: Kimi **reviewer** real-rate 0% (R1) / 20% (R2), 0–1 survived Opus. Kimi **validator** 25%
  precision both runs, **0 no-verdict holes** (GLM's disqualifier avoided), but the V arm is caveated
  (Sol@low reviewer — FINDINGS 7; V2 c4 Opus fallback — FINDINGS 9). Verdict: **keep prod pins**
  ([FINAL_REPORT.md](./FINAL_REPORT.md)).
- **Scoring join gotcha:** all four runs are `run_index=1` (each is turn-1 of its own report), so
  `issue_key`s collide across runs — join truth by **(run, issue_key)**, not `issue_key` alone.
- Harness reverted to prod (`git checkout` of the 5 posthog files: constants, utils, gateway config,
  github_meta, activities — `git status` clean, no modified tracked files). MCP scopes untouched
  (master's `llm_skill:read` + `user:read`; no `project:read`). All PR-75215 report rows deleted; DB clean.
- Local state left in place: the monorepo (`$LOCAL_POSTHOG_CODE_MONOREPO_ROOT`) still carries the
  kimi `models.ts` entry + rebuilt `dist/` (separate repo, not in the posthog commit; harmless — revert
  `models.ts` + `pnpm --filter @posthog/agent build` to make it pristine). `.env` kimi Modal creds kept.
- Cost: **~$80 total** (R1 $27.2, R2 $34.9, V1 $7.2, V2 $10.9).

## Follow-up runs (2026-09-02) — a 3rd reviewer sample + the Sol@xhigh question

Added on Alex's request: one more reviewer run (n=3 to tame the 0%/20% variance) and, if achievable,
a validator run with Sol at **true** xhigh (removing V1/V2's Sol@low caveat).

**Local-vs-prod verdict on the Sol@low bug (FINDINGS 7):** LOCAL-ONLY. Prod ReviewHog Sol reviewer
`$ai_effort` (project 2, 21 days): `xhigh` 118,870 calls (latest 2026-09-01, ongoing) vs `low` 60,279
(stopped 2026-08-26 = #88893 landing). Current prod is xhigh — no `FIX_XHIGH.md`. Root cause of the
local low: the Desktop monorepo is stale (HEAD `a4c32dfdc`, 2026-08-01, pre-fix), and the kimi overlay
builds the agent from it. Clean local V3 needs the monorepo updated past 08-26 + rebuilt (pending Alex's
go — it touches the Desktop monorepo).

### R3 — Kimi reviewer, 3rd sample (2026-09-02 05:15–06:36 UTC)

- Arm: reviewer CLAUDE / moonshotai/kimi-k3 / max; validator CLAUDE / claude-opus-5 / xhigh.
- Report `01a0608b-76c2-7af0-9e69-b2b120c5402b`, head `a7fb363b`, pinned 4 chunks.
- Funnel: dedup **19** (10 should_fix + 9 consider) → **valid 0** (opus-5 kept 0/19). Body "No issues
  to report." (real-rate: scoring in progress.)
- Effort guard PASS (Kafka): Kimi review + blind-spot @ `max`; validation `claude-opus-5` @ `xhigh`
  (85 calls across c1/c2/c4) + 3 transient `claude-opus-4-8` fallback calls (negligible; opus-5 was the
  validator). dedup + selection Sonnet 5.
- Cost: Kimi review side ≈ $13.80 ($11.02 review + $2.78 blind-spot); Opus validation ≈ $12.99
  ($11.07 opus-5 + $1.92 opus-4-8); total ≈ **$26.9**.
- Artefacts: `runs/R3-kimi-reviewer.{log,ai_usage.json,start,end}`, `findings/R3.extract.json`.

### V3 — Kimi validator with Sol@xhigh

_pending — needs the monorepo update for true Sol@xhigh (Alex's call)._
