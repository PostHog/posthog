# Resolution runs as its own Temporal workflow, not a stage of the review workflow

Reviewing (`review-pr`) and resolving comments (`resolve-pr`) are separate Temporal workflows, with the review dispatching resolution as an abandoned child after publish. Considered folding resolution into the review workflow as a post-validation stage; rejected because (1) standalone resolution is first-class — `/resolve` and inbox handoffs settle other bots' and humans' comments on PRs ReviewHog never reviewed, so a merged workflow would still need a second entry point; (2) a resolution crash must not fail an already-published review, which the abandoned-child seam gives for free; (3) two short histories version independently — editing one stage's command sequence doesn't risk non-determinism for in-flight runs of the other.

## Consequences

Cross-stage coordination is manual: Temporal's same-id joining dedups review-vs-review and resolve-vs-resolve but cannot see across the two, so "is this PR's cycle busy?" checks and stage-aware UI/status surfaces must be built explicitly (decided 2026-08-13, reaffirmed while designing resolution-stage visibility).
