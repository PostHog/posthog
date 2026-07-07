# Review-stage cost experiment candidates (prompt-caching program) — 2026-07-06

> Ideation round over the 2026-07-03 investigation (`INVESTIGATION.md`, same folder).
> Method: 4 lens-diverse generators produced 18 raw candidates, merged to 13, each adversarially audited by 2 independent
> critics (caching mechanics + economics; quality + precedent). The audit killed 3; a user decision the same day
> (see the locked constraints below) killed 3 more. 7 survive; kills are recorded in the graveyard so they are not re-proposed.
> Candidate numbering (#1-#10) is stable across kills — `PLAN.md` and ARCHITECTURE.md reference it.
> Built so far: #1's instrument (2026-07-06, validated). Everything else is a spec; per-candidate status lines carry the truth.

## Locked constraints (user; 1-5 locked 2026-07-06, 6-9 late the same day, 5 amended 2026-07-07)

1. **Quality is the moat. Not time, not money. ReviewHog must never generate bullshit.**
2. **One-shot LLM calls for code investigation are permanently out of scope.** A single call cannot do detective work —
   follow a lead, verify a suspicion, hop the call graph when it needs to. Only chunking and dedup (pure text tasks) stay
   one-shot; every unit that investigates code — wave, blind-spot, validation — stays a sandbox agent with full,
   unrestricted exploration. The program is: **make sandboxes cheaper via cache reuse, not replace them.**
3. **Large PRs (1000+ additions) are the priority** — that is where review is hardest and the product matters most.
   All experiments run per chunk (the chunker targets ~300-addition chunks), so savings scale with chunk count and large
   PRs benefit most in absolute $.
4. Scope: review stage only (wave + blind-spot), no validator experiments, no model downgrades; cost-first within the
   quality gate (a few minutes of wall-clock regression is acceptable if $/run drops); every arm passes the standard
   frozen-PR #62096 eval.
5. Working mode (amended 2026-07-07): **one branch — everything happens on `signals/reviewhog`, no per-experiment
   branches.** Experiment code lands behind an on/off constant (the `constants.py` knob pattern); arm-vs-control runs
   toggle the constant; a losing experiment's commits are reverted, and the experiment folder keeps the record.
   Experiments still run iteratively, one at a time.
6. **The fork is reframed from "harvest incidental overlap" to "design the warm-up as THE investigation stage."**
   After chunking, one neutral agent per chunk understands the chunk and the related codespace (reads, no judgments,
   no code); perspectives fork from its cached session and should not NEED to re-investigate. Perspectives keep full
   tools and freedom (constraints 1-2 unchanged — skipping re-investigation is the expected outcome, not a rule),
   and the anchoring guard (per-perspective finding-count distribution + yardstick) stays mandatory.
7. **The value case is fan-out width, not measured overlap: perspectives are user-extensible (could be 20, we don't
   limit custom perspectives), so the warm-up amortizes over N and "it should always be worth it if we make the
   cache work." The s >= 0.55 pre-build gate is DROPPED** — no overlap measurement gates the build. Measurement
   moves post-build: follower turn count / per-turn cost vs control (the saving is turn elimination) + quality parity.
8. **Fixture for the fork experiment: frozen PR #62096** (the standard eval fixture, 3 chunks) — comparable with
   every prior round. The large-PR (1000+) bucket stays untested for now, accepted.
9. **TTL policy:** default on our sandbox path is 5m (proven — see HARNESS.md "1h cache TTL"); 1h is enforceable
   with `ENABLE_PROMPT_CACHING_1H=1` in the sandbox env (per-unit, 2× write cost). Design fan-out for the 5m sliding
   window (immediate scheduling, overlapped provisioning), or selectively 1h on the warm-up unit; widen only if
   measured gaps demand it.

## Measured facts the program stands on

1. **Naive token math overstates true cost ~4.8× — and the metrology to see it is SHIPPED and validated.**
   `eval/scripts/dump_result.py` splits every gen into fresh / cache-write (1.25×) / cache-read (0.1×) / output per
   (model × stage) and matched the gateway's LiteLLM costs at Δ +0.0% on every bucket and side
   (`runs/gate0-run1-pr68749-publish.md`: naive $47.52 vs true $9.90; whole-run split 43% reads / 33% writes /
   19% output / 5% fresh — cache reads are the largest true-cost bucket). The probe-era "+28% gw-vs-list discrepancy"
   was a measurement artifact (LiteLLM's `input_cost` field is the whole input side, cache included).
   Provenance: the original 10-day probe (316.26M input = 293.84M reads + 20.17M writes + 2.25M fresh; ~$136 true vs
   ~$655 naive) mapped the model round's "naive $87-101/run" to **~$18-21/run true** on multi-chunk runs. The archived
   07-03 arm events died in the 2026-07-06 DB nuke; sonnet-era baselines accumulate from fresh runs.
2. **Cross-sandbox cache sharing is partially live, observed twice** (smoke run 2 and the PR #68749 publish run —
   the July "exactly zero" measurement is stale): 2 of 3 fresh wave sandboxes read the leader's identical 27,618-token
   [tools + system-preset] segment at turn 1 (full tables in `HARNESS.md` and the run dump; the turn-1 distribution is
   a standing section of every dump). The `Task-Id` append (V1) poisons everything after that segment, worth ~cents,
   so **the fork hard-requires T2 (byte-identical full prefix) and T3 (raw-transcript fork-seed)**. The gateway
   provably shares one Anthropic cache across sandbox processes. Wave→blind-spot gaps of 5m52s-12.5min busted the 5m
   TTL both times → fan-out needs immediate scheduling with overlapped provisioning (fresh sandbox setup alone is
   ~4-6 min), with `ENABLE_PROMPT_CACHING_1H` as per-unit insurance.
3. For the record (measured, direction vetoed): one-shot direct calls would have removed most of the sandbox-loop cost,
   and the audit scored two such candidates at ~$7-8/run. The veto stands regardless: those calls cannot investigate,
   and quality is the moat. Recorded here so the economics aren't re-derived and the veto isn't re-litigated by a future
   session — see the graveyard.

## The program (all candidates sandbox-preserving; state as of 2026-07-07)

| round                      | what                                                                                                                                   | state                                                                                                                                                                                                                                                                               |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 (measurement)            | #1 metrology + #2 gateway probe + #3 fork-sizing spikes                                                                                | **CLOSED 2026-07-06**: #1 shipped + validated; #2 optional (substrate proven live twice); #3 demoted (constraint 7 dropped the s-gate). `PLAN.md` = record                                                                                                                          |
| **ACTIVE: the fork build** | #8 under constraints 6-9 — `../2026-07-warmup-fork/` (own plan + run log)                                                              | **M1-M4 DONE, M5 HALF DONE 2026-07-07**: T2+T3 patched, Spike 2 exact-token PASS, built behind `WARMUP_FORK_ENABLED`, mechanics proven in-pipeline (5/6 followers + 1/3 blind-spots read at 0.1×); both controls in ($15.63 @ 2ch / $25.60 @ 3ch); remaining: 2 arm runs + judgment |
| queued (cheap builds)      | #4 skill-body splice + #10 pre-pack touched files (after its free pre-gate)                                                            | ~$4-7/run combined at opus-era prices — re-anchor against fresh sonnet-era controls before trusting                                                                                                                                                                                 |
| hedges (unsequenced)       | #5 Arm B (blind-spot as warm continuation turn, C5-guarded); #9 Arm A (prompt turn budget — tension with constraint 1, last if at all) | ~$2.9 and ~$3/run respectively (same re-anchor caveat)                                                                                                                                                                                                                              |

**Harness path (resolved 2026-07-06):** the fork's harness changes (T2 cache-stable system prompt, T3 raw-JSONL
fork-seed) are patched directly in the local PostHog Code checkout (`/Users/woutut/Documents/Code/code`); the proven
build/overlay/verify loop and exact patch surfaces are in `HARNESS.md`. How the fixes ship upstream is decided after
the experiment proves value.

Sonnet-5 list pricing: $2/M in, $10/M out (write 1.25× at 5m TTL, 2× at 1h, read 0.1×). Candidate $ estimates below
predate the metrology; treat them as sizing inputs and re-anchor against fresh sonnet-era controls.

---

## Survivors

### 1. `cache-aware-metrology` — cache-aware cost attribution + corrected baseline + T1 re-quantification

DEP: none (offline). Direct saving: $0 (decision value only; conditional T1 EV ~$0.1-0.15/run). Verdicts: modify + modify.
**Status 2026-07-06: instrument SHIPPED and validated (Δ +0.0% vs gateway LiteLLM on every bucket and side);
discrepancy sub-task RESOLVED (probe artifact); archived-arm recompute DEAD (DB nuke — baseline accumulates from
fresh runs). Full original spec in git history.**

Remaining open work (rides along on the fork experiment's control runs):

- **T1 rewrite detector** over fresh runs (consecutive gens in one task_run_id, time-ordered: cache_read < 0.05x prev,
  cache_creation >= 0.8x prev, gap <= 120s; sweep the creation threshold to 0.5x; classify rewrite-after-write vs
  session-restart; note the Bedrock-fallback confound). Decision: >= $0.5/run -> press the Tasks-team ticket;
  < $0.3/run -> demote and record (crude post-flip probe found ~$0.005/run, so demotion is the likely outcome).
- **Re-anchor the candidate $ estimates** (#4, #5, #9, #10) against the fresh sonnet-era control runs.

### 2. `gateway-cache-probe` — cross-client cache-share probe (Spike 1, cheap worker-side variant)

DEP: none (throwaway script). Direct saving: $0 (go/no-go information). Verdicts: modify + modify. Cost ~$0.25-0.60, ~1-3h.
**Status 2026-07-06 late: OPTIONAL.** The existential question has a production PASS (twice — smoke run 2 + the
PR #68749 publish run), and the fork build's own mechanics gate (follower turn-1 cache reads ≈ warm-up transcript)
subsumes the substrate check. Run the controlled arms only if the build's cache behavior surprises.
Post-veto re-aim: **arm 5 (sandbox-origin pair) is the load-bearing arm** — the substrate check for all cross-SANDBOX
sharing (T2/T3/#8); the direct-path breakpoint result now matters only for the one-shot chunking/dedup calls.

Byte-identical `messages.create` requests (NOT `.parse`, structured outputs inject schema bytes; thinking off; ~10K-token
document block with explicit `cache_control`) through `get_async_anthropic_gateway_client(product="review_hog")`.
Arms: (1) same-process repeat (control: does the gateway forward `cache_control` at all);
(2) two OS processes 2 min apart, **replicated >= 3x with fresh nonces, reported as a share RATE** (a gateway pooling
multiple upstream keys would share probabilistically; a single trial gives a false binary);
(3) allowlist mapping check with `$ai_model` confirmed on both sides (if a non-allowlisted name maps to the same default,
a HIT is the expected outcome, not a miss);
(4) 6-min-gap TTL sanity with a fresh nonce and guaranteed zero intermediate reads (reads refresh the sliding TTL free);
(5) **mandatory before any cross-sandbox greenlight**: one byte-identical pair issued from inside a sandbox as raw gateway
calls (network-origin/credential check; a Claude Code CLI-driven pair cannot be byte-identical today because of V1/V2
and would miss by construction).
Every arm nonce-salts its document so arms cannot read each other's entries.
Interpretation discipline: arms 2+5 PASS = workspace substrate verified; it does NOT "de-risk" the cross-sandbox program
by itself (T2/T3 byte fixes and CLI breakpoint behavior remain unproven).
Arm-1 FAIL -> gateway ticket; re-probe via a CLI-driven sandbox session pair once T2 lands (intra-session caching
demonstrably works through the gateway, so a strip would be direct-path-specific).

### 3. `fork-sizing-spikes` — exploration-overlap share s (Spike 3) + prefix-warmth TTL timeline

DEP: none (offline; data capture may ride the next eval round's controls). Direct saving: $0. Verdicts: keep + modify.
**In Gate 0: this is the flagship's go/no-go. Include large multi-chunk runs (large PRs are the priority),
reporting s per chunk-count bucket.**
**Status 2026-07-06 late: DEMOTED by locked constraint 7 — s no longer gates the build** (the reframed warm-up
targets s→1 by design, and value scales with unbounded perspective count). The warmth/TTL half is folded into the
fork build (measure gaps on its runs; `ENABLE_PROMPT_CACHING_1H` is the lever if they exceed 5m). The overlap
analysis survives only as an optional post-build diagnostic.

One extraction harness over post-flip runs, joining `$ai_generation` (timestamps, cache_creation) to the tasks' ACP logs
for tool-call arguments (`$ai_tools_called` has names only, verified).
(a) Overlap: normalize tool calls (Read path, Grep pattern+scope, classified Bash), early window = turns 2..ceil(0.4 x turns)
(reconcile with the pre-first-finding boundary as a swept variant), weight by next-gen cache_creation minus prior-gen output,
**compute s over the 3 wave units only** (strict = present in all 3; loose = 2-of-3); report the blind-spot's marginal overlap
separately (it feeds the 5th-forker decision, not the wave GO).
(b) Warmth: per (run, chunk), max consecutive inter-gen gap across the wave union (worst unrefreshed TTL window) and the
last-wave-gen -> first-blind-spot-gen gap, p50/p95, plus a simulated shift for the fork-era schedule.
Gates: wave-fork GO needs **s_p50 >= ~0.55 strict** (the audit showed net at the investigation's original 0.40 boundary sits
below the materiality bar once the re-read tax is priced); wave-internal gap p95 < 4 min -> forks TTL-safe without
rescheduling; wave->blind-spot gap p95 < 4 min -> blind-spot can be a 5th forker (+$0.8-1.1/run on top).

### 4. `skill-body-splice` — inline pinned perspective skill bodies, kill the skill-get choreography

DEP: none. Corrected saving: ~$4-4.5/run opus-era (re-measure on sonnet first; could deflate to ~$1-2.5). Verdicts: modify + modify.
Sandbox-preserving: units keep full exploration; only the skill DELIVERY changes. Custom skills fully preserved —
same per-team versioned DB rows (`ReviewSkillConfig` -> LLMSkill), same selection logic; the worker resolves the body at
prompt-build time instead of the agent fetching it via MCP mid-run.

Splice the resolved body **in place** at the existing perspective block (`prompt.jinja:83-87`), replacing the runtime
`skill-get` instruction with "your perspective is included below, do NOT call skill-get" (the MCP tool stays available;
`skill-file-get` stays for bundled files of custom user skills). Version pinned at build time, same race protection as today.
Kills the measured 2.65 fetch-choreography gens/unit (~$0.44-0.58/unit x 12 units, opus-era) for ~$0.1/run of added payload.
Turn elimination inside each unit's own working intra-session cache; no cross-unit sharing claim.
Critic-required fixes folded in: do NOT bundle the 138-line static-suffix hoist into the eval arm (worth $0 today under V1/V2
and it confounds quality attribution at n=2; apply later as a mechanical change or when T2 ships); output schema stays at the
prompt end regardless; pre-gate by re-measuring fetch-choreography $/unit from sonnet-era traces (if < ~$0.17/unit, demote).
Gates: fetch gens ~0 AND total gens/unit down ~2+ (catches turn reallocation, the named third failure mode);
cache-aware $/run down >= 15-20% vs control (relative, not the opus-era absolute);
valid findings >= control - 1; per-perspective lens-adherence rubric unchanged.
Cheapest, most composable build of the round; the strong default first BUILD.

### 5. `blind-spot-restructure` — Arm B only: blind-spot as a warm continuation turn

DEP: none. Corrected saving: ~$2.9/run ceiling. Verdicts: modify + modify (as the two-arm original).
**Arm A (direct one-shot conversion) KILLED 2026-07-06 by the user veto — see graveyard. Arm B survives as an
unsequenced, exploration-preserving hedge.**

Run the blind-spot check as one follow-up turn inside a still-warm wave unit's sandbox session (multi-turn primitives exist
in `executor.py:95-164`, validation-only today) — the host's full explored context is already in its intra-session cache,
so the follow-up reads ~150K at 0.1x (~$0.045) instead of a fresh unit rebuilding equivalent context over ~15 turns.
This is the C5-sanctioned revisit: a single same-chunk follow-up (NOT C5's cross-chunk sequential turns), carrying the
explicit anti-anchoring device the C5 verdict named as revisit precondition, extended to exclude the WHOLE wave's covered
territory, not just the host's own exploration.
Requires per-chunk firing (move blind-spot out of the per-run gather) + host = last-finishing wave unit, else the idle host's
5-min TTL lapses and a ~$0.56 full-prefix rewrite eats half the saving; "follow-up turn-1 cache_read > 0" is arm-invalidating,
not advisory. Gates: blind-spot-attributed valid findings >= control - 1; overlap-with-wave rate not higher than control
(anchoring detector); cache-aware blind-spot cost <= $1.0/chunk.
Quality risk is real (anchoring to the host's exploration path is precisely the C5 failure mode, and blind-spot exists to
find what the wave missed) — which is why this is a hedge, not the flagship.

### 8. `warmup-fork-wave` — per-chunk neutral-read warm-up + fork of the N wave units (T3)

DEP: harness (T2 + T3 + SHA-pinned checkout). Corrected saving: ~$0.7/chunk at s in [0.55, 0.6] (~$1.5-2.2/run on the
3-chunk frozen PR; scales with chunk count, so large PRs benefit most). Verdicts: modify + modify.
**THE FLAGSHIP (2026-07-06).**
**Status 2026-07-06 late: promoted to THE NEXT EXPERIMENT under locked constraints 6-9** — the gated ladder
(#3 s-gate → #2 arm 5 → Spike 2) collapses: no pre-build measurement; Spike 2 (stripped-form fork fidelity) becomes
the build's first milestone, and the substrate check folds into the mechanics gate. The $ figure above was sized at
N=3 wave units and s≈0.55 — under the reframe (warm-up = the investigation stage, N unbounded via custom
perspectives) it is a floor, not the estimate. Fixture: frozen PR #62096; standard eval (2 arm vs 2 control) with
the anchoring guard; gates = mechanics (follower turn-1 cache_read ≈ warm-up transcript), cost (follower turns +
per-turn cost drop), quality (yardstick parity). Every reviewer stays a full sandbox agent with unrestricted exploration; the
perspective-invariant share of exploration arrives pre-done as a 0.1x cached prefix instead of being re-derived 3x per chunk.

Warm-up = a real Claude Code sandbox session (tools+system must match followers byte-for-byte; a direct call cannot seed this)
that reads the diff + touched files + immediate callers with a no-analysis instruction; T3 uploads the raw session JSONL
(never the lossy ACP hydration); followers download to the identical deterministic cwd and fork, appending one user message
(static instructions + output schema + 2-line perspective block).
**Mechanics hole found by audit, fix folded in: thinking-block stripping.** A follower's appended non-tool-result user message
strips prior thinking blocks server-side, so the forked bytes diverge at the first thinking block and the ~70K fork read
never happens; the warm-up must end with a settling user turn so IT writes the stripped-form cache once (~$0.19/chunk),
and Spike 2's fidelity gate must be restated against the stripped-form prefix or it false-kills a correct implementation.
Also folded in: the re-read tax is NOT a wash if the warm-up under-covers (cap the warm-up transcript ~70K and gate
follower per-turn cost vs control, not just turn count); stagger the followers or rely on the settling write to avoid a
concurrent re-write race; Spike 2 must measure the full warm-up-completion -> follower-first-request latency against the
5-min TTL (JSONL upload + Task scheduling + provisioning — fresh sandbox setup alone measured ~4-6 min, so overlap
follower provisioning with the warm-up run; `ENABLE_PROMPT_CACHING_1H=1` on the warm-up sandbox is the per-unit
fallback, resolved 2026-07-06 — see HARNESS.md "1h cache TTL");
production follower turn-1 cache_read monitor with an auto-disable kill switch (a silent cache regression flips net negative
while functionally invisible); contingency B2 (fork a real perspective unit's mid-session transcript) is DEAD — it inherits
conflicting perspective instructions in-context and reintroduces C5-style shared analytical state.
Ladder (collapsed 2026-07-06, constraints 6-9): T2+T3 local patches -> Spike 2 (stripped-form fidelity) -> build behind a
constant -> standard 2v2 eval on #62096 with per-perspective finding-count distribution as the anchoring guard.
**Build state 2026-07-07: everything up to the eval is DONE — mechanics as built diverge from this spec in three
measured ways (two-turn fork because entries are addressable only at message ends; leader head start because
readability starts at the writer's TTFT; 1h TTL unused because the S3 transcript is the durable carrier). The
as-built truth lives in `../2026-07-warmup-fork/PLAN.md`; this spec stays as the audited origin.**
The blind-spot-as-5th-forker kernel from the killed TTL-bridge candidate rides along as a near-free sub-arm,
gated on the measured wave->blind-spot warmth and the blind-spot-unique-findings metric.
Anchoring posture: the shared prefix contains no findings or judgments, only neutral raw tool results; each perspective
branches into its own isolated forked session and may explore anywhere from there.

### 9. `turn-budget-cap` — Arm A only: prompt turn budget with batched reads

DEP: none. Corrected saving: ~$3-3.6/run standalone; NON-additive with #4/#10 (same turns). Verdicts: modify + modify.
**Flagged: in tension with locked constraint 1 (a budget nudges exploration shorter). Unsequenced hedge, run last if at all.
The hard executor cap (Arm B) is dead — no max-turns knob exists in the Tasks facade (verified), and a cap below the median
would truncate exactly the detective work the veto protects.**

Arm A = one jinja edit: a soft budget statement plus "front-load reads: request independent files in one parallel tool batch"
(same information in fewer turns, not less information). Offline pre-gate from existing telemetry: compute the per-unit turn
distribution and the measured saving from turns-above-13; if < ~$1.5/run, drop entirely.
Quality gate tightened to match the sonnet-@-high precedent (a 40% saving was killed for -1-2 findings): valid findings

> = control, and a SYSTEMATIC deficit (same yardstick finding lost in both arm runs) is a kill even at -1.

### 10. `prepack-touched-files` — pre-pack touched-file contents into sandbox unit prompts

DEP: spike-lite (free offline pre-gate mandatory). Corrected saving: ~$2-2.5/run (floor -$1.8 if agents read files anyway).
Verdicts: modify + modify. Stacks with #4 and with #8; NON-additive with #9.
Sandbox-preserving: agents keep full exploration freedom; the pack pre-feeds what they would have fetched anyway,
with exploration beyond it explicitly encouraged.

Append post-image contents of the chunk's touched files (line-numbered cat -n style so findings can anchor without re-reading;
EXCLUDE files > ~400 lines entirely and list them by name as "not included, read these yourself", never truncate silently)
after the patch JSON, inside the region already byte-identical across wave units (grows the future-shared prefix; compatible
with T2/fork work).
Mandatory pre-gate before ANY eval run, from existing frozen-PR telemetry: median count of early touched-file-reading turns
per unit must be >= 4 (net of rg/search and non-touched-file reads), and sonnet-era cache-aware $/turn re-measured;
proceed only if (avoidable turns x $/turn - $0.15) x 12 >= $2.
The arm template must also amend the contradicting static instructions ("always use cat to read entire files", exact-line
anchoring), else the turn-drop kill gate fires against the harness's own instructions rather than the hypothesis.
Fetch blobs at the ref the sandbox will actually check out (branch tip today; the SHA-pin fix changes this).
Gates: median turns/unit down >= 3 (mechanical kill switch, stop regardless of quality); valid findings >= control - 1;
off-touched-file findings not collapsed to ~0 while control > 0 (a rate comparison has no power at 2v2).

---

## Graveyard (do not re-propose without a named changed circumstance — for the veto kills, that means the user reversing the veto)

**Killed 2026-07-06 by the user veto (one-shot code investigation is out of scope; quality is the moat):**

- **`direct-cached-review-tier` (#6)** — wave + blind-spot as 4 direct gateway calls sharing one explicitly cache_control'd
  context bundle, size-gated with sandbox fallback. Audit-corrected saving ~$7-8/run (mechanics verdict: keep); killed on
  principle, not economics: a one-shot call cannot follow a lead, verify a suspicion, or hop the call graph beyond what was
  pre-stuffed, and no deterministic context pack substitutes for detective work. The audit's reusable findings are recorded
  in "Measured facts" above and in #8's spec (e.g. output_format precedes system/messages in the cache key; streaming
  writer-then-readers sequencing; per-perspective count distributions as the anchoring detector).
- **`explore-once-hybrid` (#7)** — one sandbox explorer per chunk producing a facts-only dossier consumed by 4 direct cached
  calls. Same disease: only the explorer keeps tools; the reviewers themselves cannot investigate. Audit-corrected ~$7.5-8/run.
  The "explore once, reuse via cache" idea survives ONLY in its sandbox-consumer form: #8, where every reviewer is a full
  sandbox agent forking the warm-up's transcript.
- **`blind-spot-restructure` Arm A (#5A)** — the blind-spot as one direct call per chunk with stuffed context (~$4/run).
  The blind-spot's repo sweep beyond the diff is its purpose; stuffing cannot replace it. Arm B (warm continuation turn,
  sandbox) survives above.

**Killed 2026-07-06 by the adversarial audit (economics/mechanics):**

- **`t1-t2-staggered-launch`** (T1+T2 ship + leader-first staggered wave launch). KILLED (mechanics).
  Its unique lever, staggering, is worth ~$0.4/run at sonnet prices: micro-class. The $2.4 claim booked T1/T2 harness savings
  that ship independently as tickets, used opus-era pricing, and counted a chunk-local user-prefix read that cannot happen
  (the wave units' shared span lives inside ONE content block of Task.description; cache hits occur only at
  breakpoint/content-block boundaries, and the CLI will never place one mid-block at template line 84).
  Its "production go-signal" payload is free elsewhere: blind-spot units are already natural post-wave followers, so
  post-T1/T2 telemetry on an ordinary instrumented run plus #2 flips the same T3 decision without a 6-run eval.
  T1/T2 themselves remain live as Tasks-team tickets (see INVESTIGATION.md Phase 0); only this eval wrapper is dead.
- **`blindspot-fork-ttl-bridge`** (keep-alive replay pings vs 1h-TTL bridging + cross-chunk cache-aware scheduling). KILLED (mechanics).
  The bridge solves a non-problem: wave-follower reads refresh the warm-up span's sliding TTL free for the whole wave, and the
  only real gap (the global wave barrier before blind-spots, `workflow.py:160-189`) is closed by a trivial DEP=none per-chunk
  sequencing change. The ping itself likely cannot refresh message-span blocks (thinking-config mismatch invalidates message
  breakpoints; V3-class byte-fidelity risk: ~$2.2-2.7/run of silent waste if it misses, more than the claimed saving), and the
  insurance leg rested on 12-on-10 semaphore contention the DAG cannot produce (demand is 3 -> 9 -> 3, never 12).
  Salvaged kernel: blind-spot as 5th forker + per-chunk blind-spot sequencing, folded into #8's eval as a sub-arm.
- **`batches-oneshot-stacking`** (Message Batches API 50% off stacked on the direct tier). KILLED (both critics; now also
  moot — its host, #6, is veto-killed). Honest ceiling ~$1.1-1.6/run; triple-gated behind an unproven tier, a nonexistent
  gateway batches route, and a poll-timeout design incompatible with Anthropic's no-SLA batch turnaround.

## Protocol notes

- Standard eval: 2 arm runs vs 2 controls on frozen PR #62096, LLM-judged vs the old-10 yardstick
  (`../2026-07-reviewer-topology/fixtures/`); per-perspective valid-finding-count distribution is the standing anchoring
  detector (how C5 actually manifested); yardstick finding-ID overlap catches count-preserving coverage shifts.
- Open protocol question (raised 2026-07-06, undecided): add a second frozen eval fixture — a serious 1000+ addition PR —
  so every arm is also judged where it matters most (judge-based scoring; no old-reviewer yardstick exists for it).
- All cost gates are cache-aware and RELATIVE to the measured sonnet-era control (Gate 0 = #1); opus-era absolutes
  ($0.10/turn, $19.6 review stage, $5.3 blind-spot slice) are sizing inputs only.
- Harness work (V1/V2/V3 fixes, T1-T3 in INVESTIGATION.md) lives in the PostHog Code repo. 2026-07-06: the user opened
  local two-repo experimentation — experiments may run on a locally patched `packages/agent`; shipping the fixes upstream
  is a separate, later decision.
- Validators keep fresh sessions; nothing here seeds a validator from review/warm-up transcripts.
