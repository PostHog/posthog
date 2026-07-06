# Signals agentic eval framework

Evaluates the **agentic** steps of the Signals pipeline — **research**, **repository
selection**, and **implementation** — by driving the _real_ production step functions and
grading their outputs against hand-authored ground truth.

It is the planned evolution of the `analyze_report` / `select_repo` debug commands (their
docstrings say so), and the sibling of the grouping eval (`../eval_grouping_e2e.py`): same
philosophy — **run the real pipeline, swap only the infrastructure**.

---

## Why this design

Every agentic step drives the LLM through one seam: `MultiTurnSession` (the tasks facade),
which in production spins up a sandbox agent against the LLM gateway. So the framework swaps
behaviour at exactly that seam and leaves the production prompt-building and result-collapsing
logic untouched. That single decision gives three run modes from one set of cases/scorers:

| Mode               | Backend                                                         | Stack needed                            | Use                                                            |
| ------------------ | --------------------------------------------------------------- | --------------------------------------- | -------------------------------------------------------------- |
| `replay` (default) | `ReplayMultiTurnSession` reads a recorded cassette              | none — no LLM, no DB, no Temporal       | deterministic regression + reproducible re-scoring; CI         |
| `record`           | `RecordingMultiTurnSession` wraps a live run, saving a cassette | full local stack + Docker               | capture a golden run to replay later                           |
| `live`             | the real `MultiTurnSession`                                     | full local stack + Docker + LLM gateway | measure a fresh agent's quality (what you use to ship changes) |

Replay runs the genuine `run_multi_turn_research` / `select_repository_for_team` — real
prompts, real Pydantic validation, real multi-turn result-collapsing — feeding recorded agent
texts in place of live ones. A cassette that no longer validates is a real, catchable
regression. Live mode is where ground truth grades a fresh agent and scores will vary run to
run; that is expected — evals _measure_, they don't assert pass/fail (a `--min-pass-rate` gate
is opt-in for CI).

```text
case (inputs + ground truth)
      │
      ▼
StepRunner ── invokes real step fn ──▶ MultiTurnSession seam ──▶ [replay cassette | live sandbox]
      │                                                                   │
      ▼                                                                   ▼
   output ───────────────▶ Scorers (deterministic + LLM-judge) ───▶ CaseResult ──▶ metrics / $ai_evaluation
```

---

## Quick start (deterministic, no setup)

```bash
# all steps, replay, from the repo root
python manage.py run_agentic_eval

# one step, gate at 100% (nonzero exit on miss) — good for CI
python manage.py run_agentic_eval --step research --min-pass-rate 1.0

# add LLM-as-judge scorers (needs LLM gateway env, see ../CLAUDE.md)
python manage.py run_agentic_eval --judge

# emit $ai_evaluation events to PostHog (queryable like the grouping eval)
python manage.py run_agentic_eval --capture
```

Equivalent pytest entrypoints (collected by `../pytest.ini`'s `eval_*` convention):

```bash
pytest products/signals/eval/agentic/eval_research.py --eval-mode replay
pytest products/signals/eval/agentic/eval_repo_selection.py
pytest products/signals/eval/agentic/eval_implementation.py --min-pass-rate 1.0
```

Framework unit tests (deterministic, DB-free):

```bash
pytest products/signals/eval/agentic/ \
  -o python_files="test_*.py" -o python_functions="test_*" -o python_classes="Test*" -o addopts=""
```

---

## Live mode (run the real agent)

Live/record drive the real sandbox agent. Prerequisites:

1. Local stack with the **Docker sandbox provider** (no Modal/cloud): `SANDBOX_PROVIDER=docker`,
   `DEBUG=1`, then `./bin/start`. The **temporal-worker** must run with `SANDBOX_PROVIDER=docker`
   (it provisions the sandbox); restart it after setting the env.
2. LLM gateway env (`LLM_GATEWAY_URL`, `LLM_GATEWAY_PERSONAL_API_KEY`) — see `../CLAUDE.md`.
3. **Local MCP pointed at the local instance** (required for research's data-evidence and
   repo-selection's cache query): set `POSTHOG_API_BASE_URL=http://localhost:8010` in
   `services/mcp/.env` and restart the `mcp` process. Without this the MCP validates tokens against
   **cloud** PostHog and the sandbox agent gets _no_ PostHog tools (research falls back to code-only;
   repo-selection can't query the repo cache). `_resolve_mcp_url` (process_task/utils.py) points the
   sandbox at `http://host.docker.internal:8787/mcp` automatically when `SITE_URL` is localhost.
4. A **synthetic eval project** so research has real data to query (the local dev `Hedgebox` team
   already has demo data; otherwise `python manage.py seed_eval_project`).
5. A GitHub integration on the team (repo-selection / implementation candidates). Public repos are
   cloneable even if the integration doesn't own them.

Then (`--team-id` defaults to 1):

```bash
python manage.py run_agentic_eval --mode live                       # all steps
python manage.py run_agentic_eval --step research --mode live --judge
python manage.py run_agentic_eval --step research --mode record     # saves a cassette
```

Live datasets differ from replay datasets (see `cases/*_live.py`): repo-selection candidates come
from the team's real integration, and implementation runs against a cloneable repo. Subjective
research judgments (actionability/priority) use **acceptable-range** ground truth, since a live agent
can reasonably land on more than one verdict for a given signal — the deterministic dimensions
(code paths, commits, summary) stay exact.

**Live results are measurements, not pass/fail.** A live run scores the agent and will vary run to
run; that's expected. The deterministic replay suite is the regression gate. Verified live on
2026-06-27 against the local stack: research runs and scores end to end (real findings, commit
attribution, MCP data queries); repo-selection 3/3 correct against the real repo cache;
implementation produces a real, correctly-targeted diff.

Implementation live drives the coding agent through the same `MultiTurnSession` seam: it edits the
cloned repo and returns the unified diff as structured output, which the diff scorers grade
(`runners.ImplementationRunner._run_live`). This evaluates the agent's edit-and-report capability;
the production flow additionally opens a PR.

---

## Layout

| File                                 | Role                                                                                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `datasets.py`                        | `EvalCase` + per-step case/expectation dataclasses; `SignalSpec` builder                                                                                      |
| `cases/`                             | datasets per step (`research.py`, …), `*_live.py` curated live variants, `generated/*.json` (large generated suite) + `generated.py` loader, and `cassettes/` |
| `generators/`                        | builders that produce the generated JSON from the project's real data (`generate_eval_cases`)                                                                 |
| `session_backends.py`                | `ReplayMultiTurnSession`, `RecordingMultiTurnSession`, `inject_session`, cassette context vars                                                                |
| `cassette.py`                        | recorded-turn format (load/save/cursor)                                                                                                                       |
| `runners.py`                         | one `StepRunner` per step — invokes the real step fn under a backend                                                                                          |
| `scoring.py`                         | `Score`, `Scorer`, deterministic + judge base classes                                                                                                         |
| `scorers_*.py`                       | per-step scorers (deterministic) and `scorers_judge.py` (LLM-judge)                                                                                           |
| `judge.py`                           | `JudgeFn` built on the signals `call_llm` gateway helper                                                                                                      |
| `harness.py`                         | the engine: run cases → score → results                                                                                                                       |
| `metrics.py`                         | aggregation, console report, `$ai_evaluation` capture (`$ai_eval_source = signals-agentic`)                                                                   |
| `repos.py`                           | pinned OSS repo registry (cal.com, supabase, n8n, …) + checkout/mount helpers                                                                                 |
| `project/`                           | synthetic eval-project seeding (hedgebox) + manifest                                                                                                          |
| `run.py` / `suites.py` / `_entry.py` | shared orchestration for the command + pytest entries                                                                                                         |

---

## Coverage — what the project holds and what the suite tests

The eval project (hedgebox demo, seeded by `seed_eval_project`) carries a representative **mix of
data the agent can analyze**: ~78 event types (analytics), ~62 error-tracking issues, ~37 session
replays, ~17 insights, ~5 dashboards, feature flags + experiments in varied states, and
data-warehouse tables. See `project/manifest.py` for the catalog.

Cases exercise **external signals from a mix of sources** — `error_tracking`, `session_replay`,
`github`, `linear`, `zendesk`, `conversations` — and a spread of verdicts (actionability ×
priority P0–P4). Research cases come in two flavours:

- **data-grounded** — the signal references data that actually exists in the project (e.g. the real
  "Checkout API timeout" issue, `downloaded_file` volume, the "Pricing page redesign" experiment).
  These set `expect_data_evidence=True`, so the `data_evidence_used` scorer asserts the agent
  actually queried the project via MCP — i.e. the seeded data was _picked up and analyzed_.
- **code-grounded** — the signal maps to real `posthog/posthog` code; code paths and commit
  attribution are asserted.

### Scale — generated suite for model/prompt comparison

To compare models or prompt changes you need volume, so the bulk of the live suite is **generated**
and committed under `cases/generated/*.json` (~110 research, ~114 repo-selection, ~110 implementation
≈ **340+ cases / 230+ signals**). Generation is grounded in the project's real data and templated for
variety:

- **repo-selection** — one case per real cached repo (expected = that repo; near-duplicate repos
  accepted as a set), plus ops/billing/legal **null** cases.
- **research** — one case per real error-tracking issue, top event, and experiment (data-grounded,
  `expect_data_evidence=True`), plus templated bug/feature/vague/perf cases across sources for verdict
  calibration.
- **implementation** — templated, auto-verifiable edit tasks (add function/constant, create file/module)
  with expected files + diff keywords derived from the template.

```bash
python manage.py generate_eval_cases                       # (re)generate JSON, ~110/step (needs DB)
python manage.py run_agentic_eval --mode live --sample 20  # deterministic 20-case sample per step
python manage.py run_agentic_eval --step research --mode live --sample 30 --seed 7 --concurrency 6
```

`--sample N` (with `--seed`) runs a reproducible subset so you can dial cost vs. coverage; compare the
per-metric pass rates across two runs to see if a change helped. Curated hand-authored cases
(`cases/*_live.py`) are always included alongside the generated ones.

The deterministic dimensions (code paths, commits, summary keywords, data-evidence, files-touched,
forbidden-files, diff-keywords, repo-correctness) are exact; subjective dimensions use acceptable
ranges. Grouping is covered by the sibling `eval_grouping_e2e.py`.

## Adding cases

1. Add a `*Case` to the relevant `cases/<step>.py` with its ground-truth `expected` and a `cassette` name.
2. Provide the cassette: record one (`--mode record` against the live stack) or hand-author it
   (a JSON file of ordered agent turns — see existing cassettes). The turn sequence must match the
   step (research: one finding per signal, then actionability, then priority if actionable, then
   presentation; repo selection: a single `RepoSelectionResult`).
3. Run `python manage.py run_agentic_eval --step <step> --case <id>` to verify.

## Adding a step

Add a `StepRunner` (in `runners.py`), a `cases/<step>.py` dataset, `scorers_<step>.py`, and one
line in `suites.py`. The harness, metrics, and entrypoints are step-agnostic.

## Querying results

Captured metrics use the same `$ai_evaluation` shape as the grouping eval, under
`$ai_eval_source = 'signals-agentic'` with `$ai_experiment_name = 'signals-agentic/<step>'`.
See `../AGENTS.md` for the HogQL query patterns (swap the source filter).
