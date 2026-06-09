# API deprecation watch loop

Keeps this codebase's external-API dependencies from silently going stale. A scheduled **detector**
produces a factual inventory of in-code API version pins; an **agentic research stage** reads each
vendor's real changelog (grounded in the exact pin and the fields we use) and emits a **cited**
signal into the Signals inbox (PostHog Code). Mechanical signals are dispatched to **PostHog Code**,
which reproduces the proven version-bump → data-migration → tests chain as **draft PRs**. Structural
signals are filed as issues for humans. The loop never merges and never runs a migration in prod.

See `../../API_DEPRECATION_SIGNAL_PLAN.md` for the full E2E design.

## Why there is no seeded sunset table

An earlier draft hand-seeded sunset dates in a YAML manifest. That produced confident, wrong dates
(e.g. it asserted Meta Graph `v21.0` sunsets 2026-06-09 — actually that was the Marketing-API floor,
and v21.0 was already blocked ~Sept 2025). **Deprecation truth must be researched from the vendor's
own changelog and cited — never seeded.** The schema enforces this: a `ResearchedDeprecation` with
`is_deprecated=True` is rejected unless it carries `evidence_url` + `evidence_quote`. Precision over
recall: no citation ⇒ no dated claim.

## Status

- **Detector (deterministic): implemented + tested.** Lists the real pins (WhatsApp Meta Graph
  `v21.0`, Google Ads `v21`, …) with no dates or claims.
- **Research stage (agentic): implemented.** Runs in the custom-agent sandbox; pure pieces tested.
- **Milestone 2 — dispatch + human gate: implemented.** `dispatch.py` routes mechanical+cited+confident
  findings to PostHog Code (draft PRs) and structural/uncertain ones to a GitHub issue. Routing +
  task/issue text are pure + tested; the side-effecting dispatch needs the stack.
- **Milestone 3 — Temporal schedule: implemented (dev-first).** `temporal/api_deprecation.py` +
  the `schedule_api_deprecation_check` command create a per-team schedule. Not wired into the global
  startup bootstrap, so bring it up on dev explicitly. `dispatch` is off by default.

## Run it

```bash
# Detector only — factual inventory, no DB, no network
python manage.py run_api_deprecation_detector
python manage.py run_api_deprecation_detector --json

# Research + emit cited signals into a team's inbox (needs sandbox + GitHub integration; no PR)
python manage.py run_api_deprecation_detector --research --team-id 1

# Research + dispatch: mechanical → draft PR, structural → issue (preview with --dispatch-dry-run)
python manage.py run_api_deprecation_detector --research --team-id 1 --dispatch
python manage.py run_api_deprecation_detector --research --team-id 1 --dispatch --dispatch-dry-run

# Schedule a recurring per-team check (dev-first; dispatch off by default)
python manage.py schedule_api_deprecation_check --team-id 1                 # daily, inbox-only
python manage.py schedule_api_deprecation_check --team-id 1 --dispatch      # also open draft PRs/issues
python manage.py schedule_api_deprecation_check --team-id 1 --delete

# Test the back half (emit → dispatch → PostHog Code) with a KNOWN finding, no sandbox:
python manage.py test_api_deprecation_dispatch --team-id 1 --sample meta --dispatch --repository my-org/posthog-fork
```

## Modules

| Module | Stage | Responsibility | Pure? |
| --- | --- | --- | --- |
| `extractors.py` / `scanner.py` | detector | find version pins → factual inventory | ✅ |
| `schema.py` | both | `Pin`, `ResearchedDeprecation` (citation enforced), `Classification` | ✅ |
| `research.py` | research | per-pin changelog-research prompt builders | ✅ |
| `agent.py` | research | `ApiDeprecationAgent` — researches each pin, emits cited findings | sandbox |
| `severity.py` | report | severity from the *cited* cutoff date | ✅ |
| `emit.py` | inbox | render cited findings → `SignalReport` (no PR side effects) | DB edge |
| `dispatch.py` | dispatch | route mechanical → draft PR / structural → issue | mixed |
| `samples.py` | testing | known findings to drive emit/dispatch without the sandbox | ✅ |

Tests (`test_detector.py`) cover the pure pieces with fixtures + a frozen `today` — no stack needed.

## Add a vendor

Add a `PinExtractor` row in `extractors.py` (`host_marker` + version-capture regex(es) + `file_globs`).
That's it — the research stage determines deprecation live from that vendor's changelog, so there is
nothing to seed. (The agent prompt is vendor-agnostic; it researches whatever pin the detector finds.)

## PostHog Code integration point

Dispatch to PostHog Code (the `agent-server` coding agent — **not** Claude Code) is
`Task.create_and_run(...)` in `products/tasks/backend/models.py`; the canonical "inbox → code → draft
PR" call is `products/signals/backend/auto_start.py` with `origin_product=SIGNAL_REPORT` +
`interaction_origin="signal_report"`. `dispatch.py` calls it only for mechanical, cited,
high-confidence findings, with a task prompt that instructs: bump the source literal(s); re-run the
breaking-change review and downgrade to a comment (no PR) if a contract change is found; add an
`update_hog_function_code` replace-option + tests when `persisted_per_row`; run the suite + a
migration `--dry-run`; open **draft PRs only**. Structural/uncertain → file an issue.
Proven fix shape: PRs #61214 (source bump), #61413 (data migration), #62106 (skip-uncompilable resilience).
