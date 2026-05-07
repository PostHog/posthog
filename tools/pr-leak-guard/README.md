# pr-leak-guard

Two-layer scanner that catches sensitive data — slack threads, customer
names, internal tickets, secrets — before they ship to a public PR.

PostHog's repo is public. When agents help write code, they often have
internal context loaded into their session (slack threads, Zendesk tickets,
private Notion pages). It is easy for that context to slip into a PR
description or a comment block. This tool exists to catch that.

## Layers

### 1. CI scan (`analyze_pr.py` + `.github/workflows/pr-leak-guard.yml`)

Runs on `pull_request: [opened, edited, synchronize, ready_for_review]`.

- Pulls the description via `gh pr view`.
- Strips template HTML comments so the scanner doesn't chase its own tail.
- Runs deterministic regex patterns first (offline, fast).
- If the description is non-trivial, also runs Claude (`claude-sonnet-4-6`)
  for semantic detection — paraphrased customer mentions, support-thread
  quotes, stack-trace pastes, etc.
- Posts a single PR comment with a redacted suggestion and a diff.
  Updates the same comment on subsequent edits (no spam).
- Exits non-zero only when block-severity (secret-shaped) findings are
  present. Other findings are nudges, not gates.

Authors can opt out per-PR by adding the `pr-leak-guard:ignore` label.

### 2. Pre-push hook (`pre_push_check.py` + `.husky/pre-push`)

Runs locally before a `git push`.

- Reads `<local_ref> <local_sha> <remote_ref> <remote_sha>` from stdin
  (same format every git pre-push hook receives).
- Diffs only the commits about to be pushed.
- Extracts newly-added comment lines from the diff (per-language
  comment syntax).
- Runs the same regex patterns as the CI scan.
- Block-severity hit (real secret shape) → exits 1, push aborts.
- Soft hits → prints a warning, push proceeds.
- Stdlib-only — works without `flox` / `uv` / a virtualenv.

Bypass: `git push --no-verify` (same as every other husky hook in this
repo). Set `POSTHOG_LEAK_GUARD_DISABLE=1` to suppress without
`--no-verify`.

## Files

- `patterns.py` — regex rules and the `Finding` model. Shared between
  pre-push and CI.
- `comment_scanner.py` — extracts comments from source files and from
  diff `+` lines. Per-language comment syntax.
- `llm_analyzer.py` — Claude API call for semantic detection. Optional;
  the regex pass runs unconditionally upstream.
- `analyze_pr.py` — CI entry point.
- `pre_push_check.py` — local pre-push entry point.
- `test_*.py` — unit tests (run with `pytest`).

## Running locally

```bash
# Scan a description from a file (no GitHub access needed)
python3 tools/pr-leak-guard/analyze_pr.py --description-file my-pr.md --no-llm --dry-run

# Scan a real PR (requires gh CLI authenticated)
python3 tools/pr-leak-guard/analyze_pr.py 12345 --dry-run

# Test pre-push hook against a saved diff
python3 tools/pr-leak-guard/pre_push_check.py --diff-file /tmp/diff.patch

# Tests (run isolated from PostHog's pytest config)
cd /tmp && uv run --with pytest --no-project python -m pytest \
    /path/to/posthog/tools/pr-leak-guard/ -c /dev/null
```

## Adding a new pattern

Add a tuple to `_RULES` in `patterns.py`. Each rule is
`(category, compiled regex, replacement, severity)`. Severity ladder:

- `block` — secret-shaped, fails CI / pre-push
- `redact` — internal reference an author probably did not mean to include
- `warn` — judgement call, surfaced for review only

Add a parametrized test to `test_patterns.py` covering at least one
positive and one near-miss negative — the patterns should be narrow
enough that false-positive hits stay rare.

## Trust model

- The regex pass is the floor — it works offline and is the only thing
  the pre-push hook has access to.
- The LLM pass is fail-safe: if `ANTHROPIC_API_KEY` is missing or the
  API call fails, we log it and continue with the regex result.
- The LLM is asked to return only verbatim spans, never reformatted text,
  so we can't be tricked into round-tripping the description through the
  model output. If a span doesn't appear byte-for-byte in the input, we
  drop it.
- The PR description is treated as untrusted input. The LLM prompt
  includes an explicit anti-injection notice; regex rules don't care.
