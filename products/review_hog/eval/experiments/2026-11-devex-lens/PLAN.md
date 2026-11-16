# PLAN: devex lens for changes to devex-owned files

Status: a local pilot ran, and [FINAL_REPORT.md](./FINAL_REPORT.md) has its result. The lens failed the recall, validity and cost bars below, so `reviewhog-devex-lens` stays off.
The experiment as written here, through `run_review` and with bars agreed first, has not run.

**Question:** on a PR that changes a file the devex team owns, does a Standard review with the devex lens session find problems that Standard alone misses, without adding noise?

The unit tests prove routing, cohort separation, and fan-out. They say nothing about review quality.

## Step 1: is there a gap at all

Run Standard as it is today on the case set, twice.
If it finds 70% or more of the labeled issues, stop. The lens has nothing to add, and the code should be removed.

## Case set

Merged PostHog/posthog PRs from the 60 days before the first run that change a file `hogli owners:resolve` gives to `team-devex`.
Each case is the PR at its frozen head, reviewed through `manage.py run_review` without `--publish`.

- **Defect cases, about 25.** A later fix or revert PR traces back to the case, or a human review thread on the case led to a code change.
  Write each known issue as one sentence with its file and line.
  Label every issue before the first lens run.
- **Clean controls, about 15.** No later fix and no review thread that asked for a change.
- Record the PR number, the head SHA, and the labeled issues in `cases.json` in this directory.
- Every case comes from the public repository. Do not add a case from a private incident or an internal thread.

## Arms

| Arm     | What runs                                           |
| ------- | --------------------------------------------------- |
| Control | Standard on the code-default arm set, flag off      |
| Lens    | The same, with `reviewhog-devex-lens` on for the PR |

Two runs for each arm, on the same heads.
Both arms keep the model, effort, finding cap, and dedup pins of the code defaults.

## Bars

Proposed. Agree and freeze them in this file, in a commit of its own, before the first lens run.

| Bar                                                | Needed                                                                                                    |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Labeled issues found, mean of two runs             | Lens is at least 20 points above control, and the gap is larger than the gap between the two control runs |
| Lens-only findings judged valid and minor or worse | At least 70%, by a blind judge that sees the code at the reviewed head and not the arm                    |
| Posted findings on clean controls                  | At most 0.5 more for each PR than control                                                                 |
| Control findings that the lens arm no longer posts | At most 1 in the set (dedup or the cap removed it)                                                        |
| Cost of the lens session                           | At most the median of the other lens sessions on the same PRs, from `$ai_generation` by `ai_stage`        |

A lens that fails a bar does not get its flag turned on. Change the prompt, then rerun both arms.

## What to report

- For each arm and run: issues found, findings posted, findings judged invalid or nit, cost, and the slowest session.
- For the lens session alone: findings that entered dedup (`flash_candidates` for `devex`), and which guides the session read.
- The share of the case set that also matches the routed-lens experiments' gates, so those gates can be scored again with the lens.
- Misses the lens was expected to find, each with the reason from its session transcript.

## Limits

- Issues nobody found, in review or after merge, are not in the labels.
- Two runs for each arm. Read a difference of one or two issues as noise.
- The judge is a model. Check a sample of its labels by hand.
