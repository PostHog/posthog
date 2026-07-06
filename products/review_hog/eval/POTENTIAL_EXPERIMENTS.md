> **Correction (post-synthesis, 2026-07-02):** this doc was investigated against a tree where `EXPERIMENT_PINNED_CHUNKS` was being kept as the eval instrument.
> The user has since reversed that ("remove anything experimental, only the winners ship") — the pin constant is deleted.
> Wherever the protocol below says "pinned chunks", read: temporarily re-add the pin for the eval round, re-deriving the C7 3-way split from `eval/experiments/2026-07-reviewer-topology/runs/C7-gappinned-1.md` (gotcha: the pin must take precedence BEFORE the persisted-chunk-set resume check).
> The chunker-determinism rejection's "already solved free by EXPERIMENT_PINNED_CHUNKS" holds in spirit: eval reproducibility is solved by pinning, which any eval round can re-add in minutes.

# Potential experiments — investigated, adversarially verified, tiered (2026-07-02)

18 candidates were each investigated by one agent and adversarially verified by a second, against the committed eval archive (`eval/experiments/2026-07-reviewer-topology/`), the live code, and independent ClickHouse re-runs.
This doc supersedes the seed list in `ARCHITECTURE.md` § "🎯 NEXT" item 6 ("Investigate potential experiments").
Nothing here contradicts locked items 1–5; validator-dependent work is explicitly sequenced after item 4.

> **2026-07-06:** the caching/cost thread of this registry (the T1 cache-rewrite ticket, Tier-3 warm sessions, the rejected pre-pass artefact and cache-prefix reorder) has a dedicated successor program: `experiments/2026-07-prompt-caching/` (`INVESTIGATION.md` + `CANDIDATES.md`, its own adversarially audited roster + a corrected cache-aware baseline — naive sonnet-5 $ overstates true cost ~4.8x). Read that before re-litigating any caching-adjacent item here; this doc's $ figures are opus-era.

### Measured baseline (local ClickHouse, all 17 eval runs, PR #62096 frozen)

| stage                                            | gens | in_M  | cacheRead_M | cacheWrite_M | out_K  | cost$  | avg_lat_s |
| ------------------------------------------------ | ---- | ----- | ----------- | ------------ | ------ | ------ | --------- |
| review (p1–3, isolated)                          | 1531 | 170.2 | 153.7       | 14.8         | 1495.2 | 215.05 | 11.9      |
| validate (warm sessions)                         | 604  | 42.1  | 39.2        | 2.3          | 473.6  | 47.78  | 10.0      |
| review-warm-session (C5)                         | 157  | 19.9  | 18.6        | 1.2          | 190.9  | 22.11  | 14.7      |
| blind-spot check (p4, "gap pass" in the archive) | 187  | 17.8  | 16.5        | 1.1          | 222.7  | 21.38  | 17.6      |
| dedup                                            | 26   | 2.3   | 0.5         | 1.6          | 26.3   | 11.80  | 11.5      |
| chunking                                         | 14   | 1.4   | 0.2         | 0.9          | 22.8   | 7.44   | 17.6      |

**Two reframes that change how every number below reads:**

1. `$ai_input_tokens` INCLUDES cache reads and writes — the scary "11–21M input tokens per run" headline is ~90% cheap cache reads (0.1× price). Fresh input per review unit is tiny (~16K at turn 1, ~0 after).
2. Whole experiment ≈ $326 / 17 runs ≈ **$19/run average**; the productionized shape (3 perspectives + blind-spot, 3 chunks) measures **~$24–28/run, ~23 min**.

**Verified mechanics the proposals rely on:**

- Review + blind-spot ≈ **80% of run cost** ($14.3 + $5.3/run). Validate ≈ $2.8, dedup ≈ $0.7, chunking ≈ $0.8 (fires only >400 reviewable additions). Materiality bar: a 50% dedup saving = $0.35/run = noise; a 20% review-stage saving = $2.9/run = real.
- Review-stage cost is **turn-dominated**, not payload-dominated: ~42% cache writes / 36% cache reads / 18% output / 4% fresh, at back-calculated opus-4-8 pricing ($5/M in, $25/M out — matches measured cost to 0.1%). Median 15 turns/unit; per-turn cost is flat ~$0.10 from turn 4 (linear, not quadratic). corr(turns, findings output) = 0.13 — long investigations barely emit more.
- **Only the review stage pins a model/effort** (constants.py `REVIEW_*` → `review_chunk_activity`; the blind-spot unit rides the same call). Chunking, dedup, and validate pass no pins and already run the agent-server default **opus-4-8 @ HIGH** — there is no xhigh anywhere except review. Body build and publish have **no LLM at all**.
- Sandbox provisioning is ~55s of LLM-silent dead time per stage transition; total dead time is 15–25% of wall.
- The review Postgres was wiped post-eval — `runs/*.md` + `judge_results.json` are the ground truth. Judge calls were not human-reviewed; spot-check notes on close calls.

**Shared protocol for all on-pipeline runs:** frozen PR #62096 @ ba725a897, `EXPERIMENT_PINNED_CHUNKS` = the C7 3-way split (the kept eval instrument, per item 1), strict validator untouched, serial runs (run → `eval/scripts/dump_result.py` → `reset_review_hog --yes` → next; the fixed workflow id + wipe-all make same-PR parallelism unsafe), ngrok up, judge per PLAN.md:227-229.
Archived C7 dumps are **not** byte-comparable baselines post-productionization (eval-era chunk constants, rewritten blind-spot prompt) — budget fresh control runs, and share them across Tier-1 experiments 3 and 4.

### Ship now — answered, no experiment needed (code + hygiene)

- **`issue_cleaner.py:34` status fix**: add `renamed`/`copied`/`changed` to the modified-files map. Today we pay full review cost on renamed files and discard 100% of their findings. Straight bug fix + unit test.
- **Instrument `clean_issues` drops** (no behavior change): persist dropped issues with reason (`status` / `no-line-overlap` / `file-not-in-pr`) + `is_directly_related_to_changes`. Note this is a DIFFERENT gate from the body's "Other findings" section: that section is a publish-time fallback for findings that survived dedup + validation but can't anchor an inline comment; `clean_issues` runs right after the review wave (activities.py:655), BEFORE dedup and validation, and its drops are terminal — e.g. a finding anchored on a context line of a modified file never reaches "Other findings" at all. Gates the Tier-2 routing experiment.
- **Greedy `is_test_file` regex fix** (github*meta.py:27): the pattern `.\*test[*\-]._`is commented "files starting with test\_" but has no`^`anchor, so it matches`test*`/`test-`ANYWHERE in the filename —`latest_migrations.manifest`(la**test\_**migrations) and`shortest_path.py`are classified as test files and silently excluded from review at fetch. The anchored`^test*._` two lines below already covers the intended case; delete or anchor line 27.
- **Chunker output coverage guard** (PLAN.md:246): deterministic check that every input file is assigned exactly once, retry on violation. ~20 lines; also the validity check any future chunker work needs.
- **Fix the stale comment at constants.py:23-24** ("CONSIDER is body-only context" — it renders nowhere).
- **Item-2 productionization note**: the planned dedup prompt nudge provably cannot fix 2 of the 3 observed C7 duplicate leaks — the positional pre-filter (issue_deduplicator.py:44-47) withheld one member of each pair from the LLM entirely. The prompt edit is still worth shipping; the pre-filter fix is Tier-1 experiment 2's job.
- **File a Tasks-team ticket**: mid-task full-prefix cache rewrites (24 gens, ~2.2M tokens rewritten with cache_read=0 seconds after a write, ~$0.75/run) — an agent-server cache-breakpoint issue, not ReviewHog code.

### Tier 1 — run next, in this order

Ordering logic: 1 and 2 are archive/offline work that runs today while the tree is mid-mutation, both quality levers.
3 and 4 form one on-pipeline campaign (shared control runs) with a hard sequencing window: after items 2–3 land, **before the skill-content round (item 5) mutates the canonical skills**.
5 is cheap and its data should reach the blind-spot productionizer immediately.

#### 1. Consider-cliff visibility (quality — origin: explore-quality)

**Hypothesis:** 27 of 72 validator-VALID findings across the 17 runs (37.5%) land at effective priority `consider` and are shown NOWHERE — `PUBLISHED_PRIORITIES={MUST_FIX,SHOULD_FIX}` (constants.py:25), the body renders only counts (prepare_validation_markdown.py:101,:121), and consider-only reviews skip publish entirely (publish_review.py:215-216). Surfacing them adds validated findings at zero marginal compute.
**Design:** Phase 0 ($5, 1–2h, archive-only): extract the 27 invisible findings from `runs/*.md`, one judge pass ("would the author act on this?"), human spot-check. Phase 1 (if ≥30–40% actionable): collapsed `<details>` "Worth considering" section reusing the off-diff renderer (new branch beside prepare_validation_markdown.py:140; reconcile with the chunk-header render); 2 confirm runs for body readability only. If Phase 0 says no: skip validation for reviewer-`consider` findings instead (−$0.6–1.0/run) — coordinate timing with item 4 so the validator round's baseline isn't measured on a shifted input mix. Optional Phase 2: rewrite the reviewer severity rubric (prompt.jinja Step 6) impact-based; score on the pagination finding's boundary-flip rate (valid in 16/17 runs, `consider` in 8 / published `should_fix` in 8 — a literal publish coin flip on identical code).
**Also hand to the validator round:** all 16 validator priority overrides among valid findings were downward; the raise capability never fires.
**Impact:** up to +1.6 surfaced valid findings/run (+60% over the 2.65 publishable mean); realistically less after the actionability gate. $0 LLM either way — something ships from every branch.
**Cost:** ~$5 + 1–2h; Phase 1 confirm ~$50.
**Kill:** Phase 0 actionability <30% → kill visibility, ship the validate-skip branch, record the decision (this is a data-backed re-open of the 06-30 "consider stays DB-only" call — frame it as such).

#### 2. Dedup at volume — cross-file leak replay (quality — origin: seed)

**Hypothesis:** the same-file positional pre-filter plus a pairing-free output schema cause the observed duplicate leaks (3 pairs / 2 C7 runs, incl. old #3 published twice as 2 of 6 VALID findings); routing everything to the LLM below ~25 findings + a cross-file-aware prompt + a paired `{duplicate_id, duplicate_of, reason}` schema eliminates ≥2 of 3 leaks without eating >1 distinct finding per ~30.
**Proven without runs:** deterministic replay of `_select_dedup_candidates` shows one member of leaked pairs A and B was classified `unique` and never shown to the LLM (issue_deduplicator.py:44-47, :117-119) — prompt-only fixes are structurally insufficient. All 3 leaks are cross-file (core.py impl vs tool.py wrapper, different chunks), and prod's finer chunking (300/600 vs the eval's pinned 1000/1500) makes that shape MORE frequent — ~1.5 leaked pairs/run is a floor.
**Design:** offline replay harness (`eval/scripts/replay_dedup.py`), findings parsed from the 17 dumps (~124 instances → ~25–35 hand-verified clusters bootstrapped from judge `matched_title`), fixture prior comments (16 entries — dedupe deliberately), direct opus calls (~$0.25–0.30; 14/20 archived dedup calls used zero tools, so replay is faithful; spot-check 3 cells through the real sandbox path). Sets: S1 = the real C7 leak sets, S2 = 10 pooled cross-run volume sets, S3 = all-distinct negative controls. Variants V0→V4 (bypass, +prompt merged WITH the item-2 nudge, +paired schema, contingent pairwise pass), ×2 seeds ≈ 140 calls.
**Metrics:** leak recall on pairs A/B/C + pooled; **false merges** — never measured anywhere (prod persists raw pre-dedup findings as `perspective_result` artefacts, persistence.py:159-174, so prod merges are retroactively auditable; the archive is not); zero S3 removals.
**Impact:** removes ~1.5 duplicate pairs/run from published output (C7-2's review was 17% duplicate noise) + the first measured bound on silent finding loss. Token delta ±$0.1–0.8/run = noise.
**Cost:** $40–60 + ≤1 day; no sandbox, no pipeline — fully parallel with everything else.
**Kill:** no variant cuts leaks ≥50% at ≤1 false merge per ~30 distinct findings; any S3 removal kills that variant; V3's schema dies if it shows no advantage over V2; then ship only the item-2 nudge and record.

#### 3. Reviewer-stage effort and model tiers — one combined round (mixed — origins: seed `per-stage-model-tiers` + seed `reviewer-model-retry`, merged: same toggle, same harness, shared controls)

**Hypothesis:** the review stage (80% of run cost, the only pinned stage, turn-dominated) has never had its effort or model varied (FINAL_REPORT.md:3). Opus@high retains quality at −$4–6/run; sonnet-4-6@high retains ≥5 of 6 valid at up to −$7.8/run; gpt-5.5@xhigh may surface the never-surfaced 5 (the yardstick was produced by gpt-5.5 — PLAN.md:12's explicit confound, which the locked skill-content round's premise depends on).
**Design:** one constant flip per arm at constants.py:5-7 (applied solely in `review_chunk_activity` — the blind-spot unit rides the same call, so the whole stage swaps together). Arms: **A** control opus@xhigh ×2 (~$50, shared with experiment 4; cross-check the 4 archived xhigh gap-shape runs as a free variance prior), **B** opus@high ×3 (~$55–65; early-stop after run 1 if turns/unit don't drop — the saving is turns), **C** sonnet-4-6@high ×2 (~$40; sonnet caps at HIGH; verify `$ai_model`every run — the agent-side allow-list silently falls back, ARCHITECTURE.md:2318-2319), **D** gpt-5.5@xhigh via CODEX +`full-access` (re-reverse cbfbef37d20): instrumented probe first (~$60–70; the 07-01 abandonment burned $23.6/277 gens with zero dumps, root cause unrecorded — capture worker logs this time), then ×2 (~$120–140) only if the probe passes. Codex telemetry has no task_title/cache split — window-based attribution, strictly serial.
**Metrics:** valid findings + yardstick coverage (count only the 5 catchable findings against effort arms); turns/unit; $/run by model window; wall-clock; D's headline = raw pre-validator hits on the never-surfaced 5.
**Impact:** B: −$4–6/run (−16–24%) and −3–5 min if quality holds; C: −$7.8/run **ceiling** (assumes the standard 3/5 Sonnet price ratio — the run measures actual passthrough); D: quality-only at ~2.6× measured unit cost ($5.5 vs $2.11) — even a losing D answers "skills, not model" and strengthens round 5.
**Cost:** ~$150 (no gpt matrix) to ~$350 (full), 4–6h serial.
**Kill:** B — a yardstick finding caught in both controls (and the archived prior) absent in all 3 high runs, or valid <80% of control, or saving <$2/run; fallback B′ = blind-spot keeps xhigh (~3-line split at the pin block). C — either run <5 valid, loses old #3 (17/17 archived), or junk up; a C win = adopt-as-candidate, confirm on 1–2 live PRs before flipping prod. D — probe fails twice on one root cause, or 0 never-surfaced hits and ≤6 valid in both runs.

#### 4. Dynamic blind-spots brief (quality — origin: seed; explicitly sanctioned by the user)

**Hypothesis:** the blind-spot unit is the highest-leverage single unit (2/4/2/2 valid across the 4 gap runs ≈ 40% of total valid output) but inconsistent; a per-run brief generated from whole-PR context (pr_intent + chunk map + enabled perspectives' names AND descriptions, with a hard non-duplication instruction — the authoring-scouts pattern) makes the C4-2 outlier (4 gap-valid, all agent-safety shaped) repeatable: +1–2 valid non-dup blind-spot findings/run.
**Design:** behind `EXPERIMENT_BLIND_SPOTS_BRIEF=False`. New single-turn activity launched parallel to the wave (started after `load_perspectives_activity`, awaited before the blind-spot round — ~0 net wall); output = schema-validated 3–6 sweep items ({risk_shape, why_this_pr, where_to_look, finding_looks_like} + disqualifiers, empty list allowed), persisted as a `blind_spots_brief` artefact (artefact_content.py registry, by-reference per the payload rule); injected as an optional `<blind_spot_sweep_brief>` block in the blind-spot prompt branch via `build_review_prompt` (issues_review.py:50), framed "starting hypotheses, not a quota"; best-effort — failure = pure-generic behavior. It never sees wave findings or the yardstick. **Decide the generator's shape up front:** single-turn diff-conditioned (~$0.5–0.65, measured chunking shape) or investigating agent (~$1–2, measured gap-unit shape) — either is noise on ~$24/run, but design and estimate must agree.
**Run matrix:** arm A (productionized canonical generic) ×3 vs arm B (+brief) ×3 on #62096 (gap-unit variance is 2-vs-4 on identical config — n=2 is too thin), + 1+1 on #63625, + arm C (prompt-only self-brief) ×2 only if B lifts.
**Metrics:** valid non-dup blind-spot findings (baseline avg 2.5); pre-validator plausible raw (hedges validator strictness — item 4's territory); never-surfaced-category hits (observational only — those stay item 5's); wave↔blind-spot dup leakage + junk; brief volatility across same-arm runs.
**Impact:** total valid ~6 → 7–8 (+15–30%) if it holds; +$0.5–2/run; ~0 wall.
**Cost:** 0.5–1 day impl + ~$150–250 runs; requires the productionized blind-spot step landed first.
**Kill:** B ≤ A on valid non-dup blind-spot findings in both run sets AND zero never-surfaced categories pre-validator; or junk/dup leakage more than doubles; or briefs just restate the perspectives' descriptions. Downgrade to C if C matches B.

#### 5. Inline skill bodies — drop the mandatory skill-get (tokens — origin: explore-cost)

**Hypothesis:** 100% of perspective units (99/99 — blind-spot units have no skill-get) burn avg 2.65 fetch-choreography gens finding and calling `skill-get`; 30% burn 4–6. Rendering the skill body into the prompt (the loader already reads the LLMSkill row — add `content` to the values_list, skill_loader.py:90-97) removes $0.44–0.58/unit measured marginal.
**Design:** thread `skill_body` through `LoadedPerspectiveDTO` (activities.py:210-213) and `ReviewChunkInput`; replace the skill-get block (prompt.jinja:82-86) with the inlined body under the same "this is your lens" framing (keep name+version for provenance; salience risk is the thing the A/B tests). Bodies are 3.9–4.3 KB single files, no bundled files — no payload risk (prompt is built activity-side). Do NOT touch the validator (locked item 4; its fetch costs $0.006/session) or decide blind-spot delivery here (item 2 owns it — but **send this data to the productionizer now**, before skill-get delivery re-imports a $0.44–0.58/unit tax).
**Run matrix:** 3 inline runs vs fresh controls, **pinned chunks** (unpinned n=3 is underpowered against chunk-draw variance).
**Impact:** −$1.2–3.5/run (6–15%), −6–9s/unit start, removes the per-unit cloud-MCP dependency and the fumbling tail. Quality expected neutral, gated.
**Cost:** 1–2h code + ~$65 runs.
**Kill:** any run falls below the archived quality band (<3 valid or <2/10 old-coverage), or measured saving <$0.75/run at 2 chunks. Cap inline size for custom user skills (~20KB) with skill-get fallback.

### Tier 2 — worthwhile

#### 6. Review turn-budget discipline (mixed — origin: seed `token-attribution-trimming`)

**Hypothesis:** the prompt MANDATES the long tail ("spend at least 40% of your time exploring", prompt.jinja:74; "Investigation Phase (MANDATORY)", :114); replacing it with a ~12-tool-call budget cuts median turns 15→≤12 at zero quality cost (corr(turns, output)=0.13; 15–34-turn units still missed all 5 skill-blind yardstick findings).
**Design:** edit line 74 only — it sits in the shared instructions block, so it disciplines blind-spot units too. 2 budget runs vs 2 fresh controls, pinned chunks. Optional rider: one run with narrowed `posthog_mcp_scopes` (one-line param thread at executor.py — client.py currently defaults `read_only` = the full 611-tool surface); kill the rider permanently if turn-1 input drops <10K.
**Impact:** −$2–4/run (naive cap-at-12 ceiling = 24.2% of review-stage cost) and −2–4 min (wave gated by slowest unit); rider up to ~$3/run more if it pans out.
**Cost:** ~$120–135 + judge (fresh baselines are the default, not the contingency).
**Sequencing:** run AFTER the tier round (#3) settles effort, and on frozen skills — new item-5 skills may legitimately need more turns.
**Kill:** valid <5 or old #3 lost; median turns don't drop ≥20% (soft budgets ignored → only a hard cap helps, and that's a two-repo @posthog/agent change — park it); saving <$1/run.

#### 7. Sandbox-free dedup and chunking (time + reliability — origins: explore-cost + explore-time "reclaim" Arm A, merged)

> **→ RUN (2026-07-03/04), report in `experiments/2026-07-oneshot-chunking-dedup/FINAL_REPORT.md`:** adopt dedup now; chunking after the tuned-prompt sampler batch (small-PR shatter was the one regression). Built as — the user-refined variant: one-shot path pinned to **sonnet-5 @ xhigh** (not opus) with **structured outputs** (not forced tool-use, which is incompatible with thinking), **size-gated** (`CHUNKING_ONESHOT_MAX_ADDITIONS=5000` / `DEDUP_ONESHOT_MAX_FINDINGS=50`, sandbox fallback above), 2 unpinned e2e runs + an offline chunk-plan sample instead of the 3+3 design. Gateway model policy pre-checked (`review_hog` product registered, any model).

**Hypothesis:** both stages are pure text tasks (dedup renders `CLAUDE_CODE_CONTEXT=""`; chunking's inputs are fully inline) paying ~55s sandbox provisioning each on the serial critical path; direct schema-enforced gateway calls (same model/prompt, Signals pattern — `get_async_anthropic_gateway_client()`, signals/backend/temporal/llm.py:11) are equivalent and structurally remove two failure classes.
**Design:** new `reviewer/sandbox/direct_llm.py` with forced tool-use against the pydantic schema; swap at `split_chunks_activity`'s `run_sandbox_review` call (anchor by symbol — file mid-refactor) and issue_deduplicator.py:107. **First check** the gateway's per-product model-restriction policy allows pinning opus-4-8 on the review_hog route. Equivalence: 3 forced-chunker + 3 default runs; compare chunk plans and dedup survivor sets to the archive.
**Impact:** −55–110s/run steady-state (7–11% of wall; dedup's call is conditional on positional candidates, so not universal) — and the real headline: **kills the 29% chunking schema-failure class** (4/14 tasks emitted a bare array missing the top-level `chunks` key; under 2× retries that's a live path to a failed review). Tokens ~neutral.
**Cost:** ~3–4h code + 6 runs ≈ $115–135.
**Kill:** dedup survivor sets diverge from archived behavior across 3 runs; chunk plans degrade; gateway can't pin the model.

#### 8. Scope-clean silent-drop routing (quality, gated — origin: explore-quality)

**Hypothesis:** beyond the ship-now status bug, `clean_issues` hard-drops findings anchored on unchanged/context lines and cross-file consequences — classes the prompt explicitly solicits (prompt.jinja:131,:199) and that the downstream off-diff/inline machinery (Change A, diff_position.py) can already render. `is_directly_related_to_changes` is captured and persisted but gates nothing. The eval PR was structurally blind (4 added + 6 modified, zero renames), so the archive can't size the loss — and the cleaner is a ceiling risk for locked round 5's cross-file root-cause findings (old #1's root cause lives in a file not in the PR).
**Design:** free first: archive-mine the `directly-related` flag distribution on validated findings from the dumps. Then the ship-now instrumentation accumulates prod drop telemetry. Phase 2 (gated on ≥0.5 drops/run over ≥20 prod runs, or before round 5 ships): hard-drop only not-in-PR + flag=False; route the rest (capped 5/run) through dedup+validation into the existing off-diff section. 2 runs × routed-vs-current × 3 PRs (frozen heads required; new PRs have no yardstick — judge-plausible metric only).
**Impact:** +1–3 valid findings/run on rename/deletion/refactor-heavy PRs at +$0.4–0.8/run validate cost; ~$0 on pure-addition PRs.
**Cost:** Phase 2 ~$250–300 + ~5h; earlier phases ~free.
**Kill:** telemetry shows <0.5 drops/run → keep only the status fix, record routing as rejected; routed findings' valid-rate <20% with zero judge-plausible additions.

#### 9. Test-diff visibility (quality, gated — origin: explore-quality)

**Hypothesis (revised down by verification):** test files are dropped at fetch (github_meta.py:299-300,:267-268) — but the sandbox tree at head already contains them, and coverage-gap evidence already ships in valid production-anchored findings (C3-both-1, C7-gappinned-2 both did exactly that). The genuinely blocked category is **weakened/deleted tests** (deletions invisible in a depth-1 checkout, diff dropped at fetch).
**Design:** hard precondition = find a frozen weakened-tests fixture PR; that arm is primary. Arm A only in v1 (test diffs as context; findings still anchored on production lines — no publish plumbing for test-file inline comments). Exclude test files from `count_reviewable_additions`; attach each to its production counterpart's chunk against a pinned plan. Score with the judge protocol, not validator verdicts alone (the strict validator false-kills — item 4's own finding).
**Impact:** frozen PR ~0–1 new valid (mostly a prompt-permission tweak); real upside confined to the weakened-tests category, base rate unknown. Tokens +5–15% review stage (+$1–2/run) on test-heavy PRs only.
**Cost:** ~8 runs ≈ $180–220 + fixture hunting; run only after the fixture exists.
**Kill:** zero judge-plausible test-category findings across both PRs, or junk +>2/run, or in-tokens +>20%.

### Tier 3 — someday / conditional

- **Warm per-perspective review sessions + anti-anchoring devices** (tokens; the item-3 sanctioned revisit). Verified economics: warm = $11.06/run vs matched isolated $18–19.9 wave (~39% naive), but ~half the saving is the anchoring itself and wall gets 3–4 min worse. Gates: multi-chunk PRs ≥ ~25% of prod wave spend (2 weeks of telemetry) AND item 4's positional-bias analysis first. The C5 code was deleted un-committed — rebuild cost ~1–1.5 days (validate-session helpers survive in executor.py). Arms: rotation Latin square + fresh-frame priming; adopt only at median valid ≥5, later-turn raw ≥50% of isolated, savings ≥15%.
- **Sandbox prewarm** (time; "reclaim" Arm B). ~2–3.5 min/run today, but re-size AFTER item 4 — if validation goes isolated-parallel, ~7 min comes off the critical path for free (the 9.6-min serial validate block) and the dead-time structure changes. Phase 0 (free): split the ~1-min transition into boot/checkout/agent-boot from existing StepTimer metrics; kill if boot+checkout <20s. Needs Tasks-facade warm-attach + owner buy-in; the chunking warm can't pin the PR branch (known only post-fetch). No "~25-min target" exists — don't justify against one.
- **Validator model tier (sonnet on validate)** (tokens; split out of the tier round). Ceiling ~$2.2/run; confounds item 4's mode/criteria round if run first, and the `start_sandbox_session` pin kwargs it needs are being reverted. Re-propose as a third arm after item 4 settles session-vs-isolated.

### Rejected — recorded so they aren't re-proposed

- **Chunker best-of-N / determinism (all variants: best-of-3, count-guided K=ceil(adds/300), self-consistency vote, two-phase)** — C6 pinned the "good" 3-chunk split and scored {3,4} valid, identical to single-chunk C0: structure alone isn't causal; the gap-topology 3-chunk edge ({8,6,5} vs {4}) is n=1 and unit-count-confounded; every observed coin flip happened at eval constants 250/400 (prod 300/600 removes the sizing pressure); count-guided would deterministically pin the WORSE 2-chunk structure. Eval reproducibility is already solved free by `EXPERIMENT_PINNED_CHUNKS`. Resurrection gate: ≥25% of prod PRs over the 400 gate AND a pinned 2v3 A/B post rounds 4–5 (preceded by a ~$7 draw-distribution probe at prod constants).
- **Skip the blind-spot check on 1-chunk PRs** — keep always-on, confirmed: the mechanism is per-chunk (zero cross-chunk value, structurally and empirically), 11 archived units delivered ~0.5–0.9 marginal valid/run at $1.94/unit (0.91 is a dedup-attribution-inflated upper bound; the team-scoping showcase was ALSO caught by the logic-correctness perspective in 2/15 runs — the gap unit is substantially a cheap diverse fourth draw, which still wins at $2). Prod telemetry via the `source_perspective` stamp re-checks this free; re-open only at <0.1 valid/run over ≥20 one-chunk reviews or if round 5's wave subsumes it.
- **Per-chunk blind-spot dispatch** — recomputed on all 4 gap runs: 0.0–0.95 min saved (mean ~0.6); blind-spot durations (3–10 min) dwarf the wave-finish spread, so early dispatch moves starts, not the finish of the slowest unit. Revisit only if prod shows long blind-spot units landing on early-finishing chunks.
- **MAX_CONCURRENT_SANDBOXES audit** — the cap (10) never bound in 17 runs (max simultaneous demand = 9); binds only at 4+ chunks (~1000+ additions) for ~1–3 min. It's a config lookup (prod worker `max_concurrent_activities` + Modal account limit → one-line bump), not an experiment.
- **Chunking/dedup model-effort downgrades** — combined ceiling ≤$1.5/run; dedup is the drop choke point (asymmetric quality risk for ≤$0.7); and "high instead of xhigh on validate/dedup" is moot — no stage but review runs xhigh.
- **Micro-cost sweeps** — body/publish are LLM-free (nothing to optimize); dedup prior-comments payload trim <$0.2/run; cache-prefix template reorder ~$0.10/run; retry token burn ≤$0.44/run worst case; prompt-payload trims (JSON→raw hunks, comment trim, scaffold diet) <$0.5/run combined. The one real anomaly (mid-task cache-rewrite churn, ~$0.75/run) is a Tasks/agent-server issue — ticket filed, not a ReviewHog experiment.
- **Shared repo-orientation pre-pass artefact** — turn-1 cache_read median is 0: no cross-sandbox cache sharing exists, so it's pure added payload per unit, plus an anchoring device of exactly the kind item 3 warns about.
- **File-bucketed dedup** — all 3 observed leaks are cross-file (impl vs wrapper); bucketing by file guarantees every observed leak.
- **First-turn fail-fast / poll-budget tuning (all variants, incl. threading `max_poll_seconds` into review turns)** — the one observed 30-min zero-gen wedge was local infra (ngrok/Modal relay; the sandbox layer was already erroring minutes earlier), self-healed via Temporal retry in ~7 min, and the prod path lacks the tunnel. Rejected as overengineering; revisit only if prod shows zero-gen wedges at the activity budget.
- **Warm-session context compaction** — `MultiTurnSession` exposes no transcript-trim/clear; unavailable without a Tasks facade change, and not worth building one for.
