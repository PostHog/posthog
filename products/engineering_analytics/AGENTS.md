# Engineering analytics — read the contract before designing

This is an isolated product with an explicit, locked engineering contract. Before designing or changing
anything here, read both in full — don't re-derive what's already decided (you'll get it subtly wrong):

@SPEC.md
@README.md

The decision most often re-derived wrong: **CI ↔ PR linkage is by PR number (the run's `pull_requests`
association), never head SHA** — a head-SHA join silently drops every push but the latest, because the
`github_pull_requests` snapshot keeps only the current head. See SPEC §7 (Locked decisions). head SHA is
a per-commit precision key only; `head_branch` is the capture-time / fork fallback.
