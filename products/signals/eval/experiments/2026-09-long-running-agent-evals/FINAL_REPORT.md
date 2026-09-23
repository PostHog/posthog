# Long-running agent evals, round 1: the API-quality scout on three models

Run 2026-09-22 on the internal dogfood project. 12 dry-run copies of the API-quality scout (3 models × 2 fixed sets of 100 backend API files × 2 runs), one prompt (the production skill), judged with rubric v0 by a Claude-family judge with a skeptic pass and a pooling step. Plan: [PLAN.md](./PLAN.md). Rubric: [fixtures/rubric-v0.md](./fixtures/rubric-v0.md). Rows: [results/runs.csv](./results/runs.csv), [results/findings.csv](./results/findings.csv), [results/decisions.csv](./results/decisions.csv).

## Result

| Model                     | Effort that ran | Runs | Reports filed | Real, in scope, new | Severity right | False | Mean recall | Cost per run | Cost per real finding |
| ------------------------- | --------------- | ---- | ------------- | ------------------- | -------------- | ----- | ----------- | ------------ | --------------------- |
| gpt-5.6-luna              | medium          | 4    | 0             | 0                   | 0              | 0     | 0.00        | $0.10        | none                  |
| gpt-5.6-terra             | medium          | 4    | 2             | 2                   | 2              | 0     | 0.38        | $0.75        | $1.50                 |
| gpt-5.6-sol (current pin) | low             | 4    | 3             | 2                   | 1              | 1     | 0.50        | $1.58        | $3.16                 |

Recall is the share of the pooled verified findings on the run's file set that the run filed. The pool has 3 entries: batch-import list pagination (set 1), health-issue resolve scope and file-system shortcut list pagination (set 2). A fourth real finding on set 1 (role external reference pagination) is excluded because experiment memory contamination pre-empted it (see below).

**What the numbers say.** Luna at medium effort filed nothing in four runs. Its "already covered" declines were correct (three of three verified against real inbox reports and PRs), but it missed every new defect. Terra filed two reports, both verified real, in scope, new and at the right severity, at half sol's cost. Sol filed three: two real (one overstated as P2 where P3 fits) and one false positive (SCIM request logs: the model already orders by `-created_at, -id`, which the copy did not read). Sol also ran at effort "low" because that is its default and the config pin cannot carry an effort.

**What the numbers cannot say.** Two runs per model per set is at the noise floor: terra found the set-1 defect in one run and not the other, and no set-2 copy of any model found the file-system shortcut defect. Terra versus sol is not settled; luna versus the other two is (four quiet runs on files where two real defects existed).

## Judge agreement and severity

- All five filed reports passed the traced and evidence items. Four of five are real; the skeptic refuted none of the four.
- Severity: the judge held two P2s and downgraded two P2s to P3 (managed-migrations by sol b10, role external reference by luna's trial). The rubric's P2 wording ("realistic, repeatable user-impact failure") is being applied strictly; the scout's own P2 definition is looser. Decide which wins before round 2.
- Declined candidates: 4 of 7 declines were correct and their coverage claims true. 2 were wrong (role external reference, file-system shortcut: real, uncovered, should have been filed). 1 was right for the wrong reason (SCIM logs: three copies said the model file was outside their allowed set, but reading a model traced from a page file is allowed; the fourth copy filed it and was wrong).

## Contamination and one production side effect

- Memory prefixes leaked. Every copy wrote only under its own `api-quality-b<n>` keys, but the scout searches memory by text, and `finding:api-quality` matches `finding:api-quality-b1`. So copies read each other's entries. Set-1 copies read b1's trial entry and declined the role external reference defect as "already found by a sibling"; two set-2 copies read b4's entries.
- The first trial run (before the prefix rule) wrote one unprefixed entry. The production API-quality scout read it on its 15:37Z scheduled run and filed inbox report `01a0c9c4` (P2, ready, with an implementation task started). The defect is real, so nothing wrong shipped, but an experiment finding became a production report through shared memory.
- Every copy learned it was in dry run from the project profile tool. Copies were told to file anyway; all did, which is what put the report payload in the log.

## Hard checks

12 of 12 runs: completed in 3 to 6 minutes, checked out the pinned commit (fetch, checkout and printed hash in the log), read only page files plus files traced from them, wrote memory only under their own prefix. Cost per run from generation events: luna $0.06 to $0.14, terra $0.50 to $0.98, sol $1.46 to $1.68.

## Judging cost

20 agents, about 2.1M tokens: 6 report judges, 5 skeptics, 7 decision judges, 1 pooling agent, 1 reader.

## What to change before round 2

1. Scope memory reads, not only writes: an experiment copy must not see other copies' entries, and production scouts must not see experiment entries. Instruction-level prefixes do not do this; it is a product change (see PRODUCT_CHANGES.md in the playground notes).
2. Pin effort per copy so models compare at the same effort. Today sol runs "low" and the others "medium".
3. Settle the P2 definition for the judge before rerunning.
4. Rerun the same two sets with the same three models at N=3 to move off the noise floor, then add a prompt variant (the SCIM false positive and the two wrong declines point at the "traced files are in scope" rule).

## Cleanup

Copies b1 to b12 stay disabled and dry-run; delete them and their `api-quality-b*` memory entries when the batch is closed. The production report `01a0c9c4` stays: it is a real defect.
