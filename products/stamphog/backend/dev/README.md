# stamphog dev runner

`run_scenario.py` is a laptop-runnable smoke of the stamphog full chain: a signed GitHub webhook
driven through review, merged-PR capture, and the daily Slack digest, with a readable printed trace.

This is **dev-only** code — not imported by production and not part of the test suite.

## Where the real coverage lives

The deterministic, CI-gated coverage is in the pytest suite:
`products/stamphog/backend/tests/test_integration.py`.
Those tests fake all four boundaries and assert the chain-level regressions
(webhook -> review -> approve, merged-PR eligibility gate, digest auto-provision + Slack post,
repo-declared channel routing, disabled-channel opt-out).

The reusable fakes (`GitHubRecorder`, `FakeSlackIntegration`, the sandbox fake, and the webhook
signing helpers) live once in `products/stamphog/backend/tests/fakes.py`. This runner imports them
directly, so there is no parallel fake setup.

## What this runner adds

The one thing the tests deliberately skip: running the review through a **real** docker/Modal
sandbox against a real LLM key, and printing the digest Block Kit so a human can eyeball it.
GitHub and Slack stay faked; only the sandbox is real when asked.

## Run it

From the repo root, with the dev stack up (`./bin/start` — Postgres + Redis):

```bash
flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/run_scenario.py'
```

Real-sandbox smoke (needs a real LLM key and a sandbox backend):

```bash
SANDBOX_MODE=real SANDBOX_PROVIDER=docker ANTHROPIC_API_KEY=sk-ant-... \
  flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/run_scenario.py'
```

Use `SANDBOX_PROVIDER=MODAL_DOCKER` (plus a logged-in `modal token`) to run on Modal instead of
docker. A real sandbox clones the target repo, so point `REPO` / `INSTALLATION_ID` at something the
App credentials can actually reach for a true end-to-end run.

If the stamphog product DB is missing (`relation "stamphog_..." does not exist`), create it once:

```bash
flox activate -- bash -c 'DEBUG=1 ./manage.py migrate_product_databases'
```

### Env knobs

- `SANDBOX_MODE=stub|real` — `stub` (default) injects a scripted APPROVED verdict; `real` runs the
  production sandbox
- `KEEP=1` — leave the scenario rows in place instead of deleting them at the end

## Why the DB shim

The runner keeps a small `_TxShim` (task `atomic()` on the stamphog writer + inline `on_commit`)
because it executes under `manage.py shell`, outside pytest's product-DB fixtures. The pytest suite
gets that plumbing for free from its fixtures and uses no shim.
