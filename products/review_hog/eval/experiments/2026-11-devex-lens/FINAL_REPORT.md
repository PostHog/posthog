# FINAL REPORT: devex lens pilot

**Question:** on a PR that changes a file the devex team owns, does Standard with the devex lens find problems that Standard alone misses, without adding noise or hiding Standard's findings?

**Short answer:** the lens adds a small number of real findings and takes nothing away, but it fails three of the five bars in [PLAN.md](./PLAN.md).
The flag `reviewhog-devex-lens` stays off.

- It found 13 and 14 of 21 findings that a human reviewer had posted, against 10 and 11 for Standard alone.
- On a second set of 26 known major issues it found 1 more than Standard, which is the size of the judge's own noise.
- It caught one defect that shipped and was fixed by a later PR, which Standard missed on every head that carried it.
- It displaced no Standard finding in any run.
- Of the 9 new root causes it posts on the second set, 5 are valid and minor or worse, which is 56% against a bar of 70%.
- Its session costs 1.5 to 1.7 times a shipped lens session, which adds about 30% to the tokens of a routed review.

This is a local pilot, not the experiment in the plan. See [Limits](#limits).

## Setup

- **Sessions.** The product's own prompt code rendered the main, lens and devex prompts for each PR head.
  Each session ran through `codex exec` read-only on the Standard arm (`SINGLE_AGENT_FLASH_ARM`) in a checkout of the reviewed commit.
- **Control** is the main session and the two shipped lenses. **Treatment** adds the devex lens session.
  Both arms share the same control sessions, so a difference comes from the lens alone.
- **Judge.** Sonnet 5.5 at high effort, with read-only git tools in the checkout.
  It saw the pooled findings of all sessions in random order, without the session names.
  One call matched findings to the labeled issues, and one call judged each finding as valid or not, with a severity.
- **Dedup and cap.** A model call with the product's dedup instructions grouped findings by root cause.
  The score then applied the product's rules: the main finding survives, then pass order, the survivor takes the group's highest priority, and the first-review cap applies.
- **Cases.** [cases.json](./cases.json) lists the pilot set and the clean set with their head SHAs and labeled issues.

## Pilot set: findings a human reviewer posted

9 PR heads with 21 findings from one reviewer's posted review comments.
8 of the 9 change a devex-owned file. The ninth does not, so the lens does not run on it, and its 2 findings count as missed.
5 PRs were used to revise the prompt, and 4 were held out.

| Arm                              | Run 1    | Run 2    | Held-out PRs (9 findings) |
| -------------------------------- | -------- | -------- | ------------------------- |
| Standard alone                   | 11 of 21 | 10 of 21 | 5 and 5                   |
| With the lens, first prompt      | 14       | 12       | 6 and 5                   |
| With the lens, second prompt     | 14       | 15       | 6 and 7                   |
| With the lens, the prompt in use | 14       | 13       | 6 and 6                   |

Every finding in this table also posts after dedup and the cap.

The prompt in use is the second prompt with a stricter severity guide.
The second prompt rated minor problems as must-fix: the judge rated 3 of its 16 must-fix findings major or worse.
A must-fix finding posts outside the cap, so that prompt could not ship.

| Session, two runs      | Findings | Valid | Valid and minor or worse | Invalid | Must-fix findings judged major or worse |
| ---------------------- | -------- | ----- | ------------------------ | ------- | --------------------------------------- |
| Devex lens             | 39       | 39    | 37                       | 0       | 6 of 10                                 |
| The two shipped lenses | 31       | 31    | 29                       | 0       | 9 of 12                                 |
| Main                   | 31       | 30    | 28                       | 1       | 4 of 5                                  |

- **New root causes the lens posts:** 6 in each run on the 8 routed PRs, all judged minor. The other lens findings repeat a Standard finding and lose to it in dedup.
- **Standard root causes the lens arm no longer posts:** 0 in all six runs.
- **Clean PRs:** on 6 PRs with no known issue, the lens wrote 2 findings and posts 1 after dedup. The judge rated both valid and minor.

### A second check on the judge

The judge rated nearly every finding from every session valid, so its precision numbers are weak evidence.
A stronger model then tried to refute the 40 findings of the second prompt at the reviewed commits.

- 28 held as stated, 11 were real but overstated, 0 were false, and 1 could not be decided from the repository.
- By its severities, 2 were critical, 2 major, 30 minor and 6 nit.
- This pass was not repeated for the prompt in use.

## Second set: known major issues, labeled independently

22 PR heads that change devex-owned files, with 26 major or critical issues that reviewers or a later fix PR had raised.
The labels were made before this work and by a different process.
One run of each arm, with the second prompt and then the prompt in use on the same control sessions.

| Measure                                            | Second prompt | Prompt in use |
| -------------------------------------------------- | ------------- | ------------- |
| Known issues found, Standard alone                 | 18 of 26      | 19 of 26      |
| Known issues found, with the lens                  | 19            | 20            |
| Lens findings, and how many the judge rated valid  | 54, 50 valid  | 49, 48 valid  |
| New root causes the lens posts after dedup         | 9             | 9             |
| Of those, major or worse / minor / nit / not valid | 4 / 2 / 1 / 2 | 2 / 3 / 3 / 1 |
| Standard root causes no longer posted              | 0             | 0             |

The Standard sessions are the same in both columns.
The two counts differ because the judge matched one issue differently, so a gain of 1 is inside the judge's noise.

The lens found one defect that no reviewer had raised.
[#105972](https://github.com/PostHog/posthog/pull/105972) stored a float array field that the saved-query metadata could not read back, and [#106886](https://github.com/PostHog/posthog/pull/106886) fixed it later.
Four heads in this set carry that line.
Standard missed it on all four. The lens found it on 3 with the second prompt and on 1 with the prompt in use.

## Cost

| Session                | Median tokens, pilot set | Median tokens, second set |
| ---------------------- | ------------------------ | ------------------------- |
| Devex lens             | 90k                      | 89k                       |
| A shipped lens session | 53k                      | 58k                       |
| Main                   | 88k                      | 84k                       |

The lens session adds 31% to the tokens of a routed review on the pilot set and 29% on the second set.
It reads the repository's guides, which the shipped lenses do not.

## Against the bars in the plan

| Bar                                                       | Result                                                                   |           |
| --------------------------------------------------------- | ------------------------------------------------------------------------ | --------- |
| Labeled issues found: at least 20 points above control    | 14 points on the pilot set (64% against 50%), 4 points on the second set | **Fails** |
| Lens-only findings valid and minor or worse: at least 70% | 6 of 6 in each run on the pilot set, 5 of 9 (56%) on the second set      | **Fails** |
| Clean controls: at most 0.5 more posted findings per PR   | 0.17                                                                     | Passes    |
| Control findings no longer posted: at most 1              | 0                                                                        | Passes    |
| Lens cost: at most a shipped lens session                 | 1.5 to 1.7 times                                                         | **Fails** |

The plan sets the validity bar on lens-only findings, which are the new root causes the lens posts after dedup.
Of all lens findings, 95% on the pilot set and 84% on the second set are valid and minor or worse. The plan sets no bar on that share.
The stop rule in the plan did not fire on the pilot set, where Standard found 50%.
On the second set Standard found 69% and 73%, which is at the 70% line.

## Limits

- **Not the production path.** Sessions ran through the local Codex CLI, not `manage.py run_review`. A different model made the dedup call than the product uses.
- **The pilot labels come from one reviewer**, and that reviewer used a devex-specific review agent. The pilot set therefore measures agreement with that kind of review. The second set does not have this bias.
- **The bars were not agreed before the first run**, as the plan asks. They were written before the runs that this report scores, except the first run of the first prompt.
- **The prompt was revised after its misses were read**, on the held-out PRs too. The second set was not used to revise any prompt.
- **Small sets.** 9 and 22 cases, 6 clean PRs, two runs. Read a difference of one or two issues as noise.
- **The judge is a model.** The refutation pass covers one prompt on one set.
- **One line of the prompt changed after the runs.** The runs told the session to read an edited guide at the merge base with git. A review sandbox has a shallow clone and no merge-base SHA in the prompt, so the prompt now points at the removed lines of the session's diff, which holds only the devex-owned files. Three words also changed to American spelling.

## What this supports

- The lens does not make a Standard review worse on these sets.
- The gain is small: about one new posted root cause for every two routed PRs, most of them minor, and a serious one now and then.
- The cost is real.

Before the flag goes on, run the plan's experiment through `run_review`, or turn the flag on for a few devex PRs and compare the reactions on `flash-lens-devex` findings with those on the other sessions.
