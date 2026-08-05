# Engineering analytics: read the contract before designing

This is an isolated product with an explicit, locked engineering contract.
Before designing or changing anything here, read both in full; don't re-derive what's already decided (you'll get it subtly wrong):

@SPEC.md
@README.md

The decision most often re-derived wrong: **CI ↔ PR linkage is by PR number (the run's `pull_requests` association), never head SHA**.
A head-SHA join silently drops every push but the latest, because the `github_pull_requests` snapshot keeps only the current head.
See SPEC §6 (Locked decisions).
head SHA is a per-commit precision key only; `head_branch` is the capture-time / fork fallback.

The one sanctioned exception, so you don't "fix" it back: `commit_pr_number` joins a default-branch run's `head_sha` to a **merged** PR's `merge_commit_sha`.
That is a different key from the banned one: terminal and immutable after merge, one commit per PR, so it drops nothing.
It stays correct only while gated on `merged_at` (open PRs carry a throwaway test-merge SHA) and deduped to one row per SHA (a raw join fans a run row out and multiplies downstream counts).
