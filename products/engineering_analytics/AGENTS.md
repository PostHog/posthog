# Engineering analytics

Read both files in full before you change anything in this product. They hold the locked decisions.

@SPEC.md
@README.md

Read [frontend/AGENTS.md](./frontend/AGENTS.md) before any frontend change. It holds the layout, comparison and table rules.

## CI to PR linkage

A CI run must resolve to a pull request through `pr_number`, the run's `pull_requests` association, and never through the head SHA.
The `github_pull_requests` snapshot keeps only the current head, so a head-SHA join drops every push except the latest.
`head_branch` is the fallback for fork runs. See SPEC §6, Locked decisions.

Two exceptions are correct. Do not change either one back.

1. `commit_pr_number` joins a default-branch run's `head_sha` to a merged pull request's `merge_commit_sha`. The join must filter on `merged_at` and keep one row per SHA.
2. A merge-queue gate run takes `pr_number` from its branch name, because its association names the temporary pull request the queue opened. `logic/merge_queue.py` defines the branch patterns once.
