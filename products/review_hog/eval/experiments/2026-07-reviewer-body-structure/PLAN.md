# Reviewer-body-structure experiment — structured finding bodies (arm S) vs prose control

> **Working scratchpad. Survives compaction — update the Run log + Decisions as we go.**
> This is the eval gate for Phase 2 of the comment-readability design (ARCHITECTURE.md
> "comment readability: staged source restructure"; vocabulary in `../../CONTEXT.md`).
> Phase 1 (validator argumentation → verify-don't-restate bullets) is already in the tree and applies
> to BOTH arms, so it does not confound. Do NOT roll Phase 2 into prod before this round's decision
> rule passes.

## What arm S changes (exactly one thing: the finding body's SHAPE)

`Issue.issue`'s field description (`reviewer/models/issues_review.py`) + a matching output instruction
in `prompts/issues_review/prompt.jinja` (+ regenerated `prompts/issues_review/schema.json`): the body
becomes labeled markdown bullets — `- **What breaks:**` (the defect), `- **Trigger:**` (the concrete
input/state that hits it), `- **Evidence:**` (file:line facts from the investigation), `- **Impact:**`
(the consequence and who hits it) — under an explicit "same information content, never omit detail"
mandate. The content is unchanged by design; the round exists to verify the mandate actually holds and
the downstream stages (validator, dedup) don't degrade. Apply the edits locally for the round only;
rollout is the decision.

## Config matrix

| label          | finding body               | runs | source                                                                                          |
| -------------- | -------------------------- | ---- | ----------------------------------------------------------------------------------------------- |
| `CTRL-prose-N` | current free prose         | 2    | this round — fresh (Phase 1's argumentation change post-dates every archived run, so no reuse) |
| `S-bullets-N`  | labeled bullets (mandated) | 2    | this round                                                                                      |

Same frozen PR `https://github.com/PostHog/posthog/pull/62096` at head `ba725a89` (re-verify
pre-flight); re-add the chunk pin per `POTENTIAL_EXPERIMENTS.md`'s 2026-07-02 correction (the pin must
take precedence BEFORE the persisted-chunk-set resume check). Prod models/efforts as of 2026-07-17 on
both arms. NO publish on any run.

## What to measure (parity, not improvement — the bar is "no quality loss")

1. **Validator verdict parity** — raw→dedup→valid funnel vs control; judge-assessed verdict
   correctness per the established protocol (old-10 root-cause coverage + new-finding plausibility,
   see `../2026-07-reviewer-model-sonnet5/` and `../2026-07-pipeline-models/`); junk leakage stays ~0.
   The fear this round exists to test: does a bulleted claim make the validator misjudge?
2. **Dedup parity** — collapse behavior on the same underlying findings (no new false-merges of
   distinct problems, no missed merges of same problems). Bulleted bodies feed dedup's fresh payloads
   directly.
3. **Mandate adherence** — for each S body: are the defect, trigger, evidence anchors (file:line), and
   impact all present? A body that dropped a fact its control counterpart carried = a mandate
   violation; count them. This is the compression-creep detector.
4. **Readability** — the user eyeballs S bodies vs control (the whole point of the change); no metric,
   just a verdict.

## Scoring & decision rule

Judge each dump per the established protocol (`judge_results.json` here, report → `FINAL_REPORT.md`).
**Adopt** arm S if the valid-finding set is judge-equivalent to control (no real finding lost, junk
leakage unchanged), dedup behavior is in the control band, and mandate violations ≈ 0. **Kill** (or
tighten the mandate wording and re-run) if evidence/anchors get dropped or verdicts shift materially.
User reviews judge calls at the end.

## Decisions (locked)

- Phase 2 ships only on this round's pass — no early rollout (user, 2026-07-17).
- The mandate is structural only: "same information content, never omit detail" is part of the arm-S
  prompt text, not an aspiration (user, 2026-07-17).
- Controls must be fresh runs — Phase 1's argumentation change post-dates every archived run.

## Run log

| label | run | date | chunks | units | raw→dedup→valid | total tok (in/out) | wall-clock | dump file | notes |
| ----- | --- | ---- | ------ | ----- | --------------- | ------------------ | ---------- | --------- | ----- |
