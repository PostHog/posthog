# FINDINGS — ops traps and environment facts (GLM 5.3 Flash experiment, 2026-08-31)

Reliable notes for future experiments. Read this BEFORE re-running anything on this machine.
Run-by-run results stay in [PLAN.md](./PLAN.md); this file carries the traps.

## Environment / harness traps hit tonight

1. **A fresh local DB loses two things the pipeline needs.** After a DB reset: (a) the GitHub
   integration is gone — only the user can recreate it (install the GitHub App via the UI;
   `Task._build_task` fails with "Team 1 does not have a GitHub integration" until then); (b) the
   DB-synced ReviewHog skills are gone — the review pipeline reseeds them itself at run start
   (`sync_canonical_*` in `temporal/activities.py`), but standalone smoke tests must seed them
   first (call `sync_canonical_*` from a shell).
2. **GLM 5.3 Flash is Baseten-exclusive in the gateway.** No Cloudflare/Modal fallback (the local
   Modal endpoint only hosts GLM 5.2). Needs `LLM_GATEWAY_BASETEN_API_BASE`
   (`https://inference.baseten.co/v1`) + `LLM_GATEWAY_BASETEN_API_KEY` in the repo root `.env`
   (get the key from the gateway's production secret store).
   Without both, NO product advertises the model and the agent silently drops it.
3. **The background_agents allowlist trap (sol-arm incident, again).** ReviewHog sandboxes call
   the gateway as product `background_agents`. GLM 5.3 Flash needed two local config edits in
   `services/llm-gateway/src/llm_gateway/products/config.py`: add it to
   `background_agents.allowed_models` AND add `"background_agents"` to its
   `RESTRICTED_MODEL_PRODUCTS` entry. Both marked `EXPERIMENT local-only, revert`. Restart the
   `llm-gateway` phrocs process after (it sources `.env` at start). Probe before any run:
   `curl localhost:3308/background_agents/v1/models` must list the model.
4. **The "missing scope: project:read" log line is a red herring — and the scope is a security
   footgun, do NOT grant it.** A later investigation (2026-08-31) disproved the first read: the
   MCP handshake's project fetch is best-effort, so `project:read` is NOT required to connect —
   the only scope whose absence refuses the connection is `user:read` (the real silent-failure
   class, fixed in #88697). A `project:read` addition was tried, then dropped: it buys only
   attribution, but `GET /api/projects/<id>/` returns the team's UNMASKED `secret_api_token`
   (plain serializer field, no redaction), which an injectable session reading untrusted PR text
   must never reach. The token is team-scoped so it is not cross-team, but leaking the reviewed
   team's own secret is enough. ALWAYS smoke `skill-get` in a sandbox before an experiment night.
5. **⚠️ READ BEFORE TRUSTING THE FINAL REPORT — GLM cannot fetch its skill on the default MCP
   surface, so this experiment runs a local MCP-mode override.** Since #69629 (2026-07-09) the
   MCP server defaults every non-allowlisted client (sandbox agents included) to CLI mode:
   exactly one tool, `exec`, whose command list covers `skill`. The ReviewHog prompts still
   instruct `skill-get(skill_name=..., version=N)`; capable models (Sol / Opus / Sonnet in the
   K/L/M/N/P control runs) bridge that by running the fetch through `exec`. **GLM 5.3 Flash does
   not**: given the pipeline's exact wording it ran four tool searches, saw `mcp__posthog__exec`
   in the results, never called it, and reported the skill missing (smokes 1–4, 2026-08-31).
   Decision (Alex, 2026-08-31): run the experiment with `x-posthog-mcp-mode: tools` forced in the
   sandbox MCP headers (`process_task/utils.py`, marked EXPERIMENT local-only) so every arm gets
   a literal `skill-get` tool. **Comparability caveat for the final report:** the GLM arms fetch
   their skills through an easier surface than the 08-26 controls did (same skill content,
   different mechanics), and prod GLM would need the same override or it reviews blind.
   Mode selection lives in `resolveMode` (`services/mcp/src/hono/request-state-resolver.ts`).
   Smoke prompts must mirror the pipeline's imperative wording, not paraphrase it — a literal
   "is there a tool named skill-get?" phrasing false-negatives on the exec surface.
6. **Local `$ai_generation` ingestion is down (again).** Zero events land in ClickHouse; the
   events sit unconsumed in Kafka topic `events_plugin_ingestion_ai`. Cost/effort ground truth =
   `../2026-08-validator-model-sol/scripts/kafka_ai_usage.py` (works: it priced the GLM smoke at
   $0.02, effort `max` on all 7 calls).
7. **The worker wedge during local Modal image builds is real and repeatable.** The image build
   rewrites `products/posthog_ai/dist/skills/*.py`; nodemon restarted the temporal worker 27
   times mid-build; the surviving worker had a wedged workflow poller (pending workflow task
   sitting unpicked while activities completed). Remedy per ARCHITECTURE preflight: restart the
   temporal worker via phrocs; in-flight `MultiTurnSession.start` polls ride through.
8. **Codex retry hack re-applied for agent 2.4.114.** Upstream only landed a 90 s sandbox
   `stream_idle_timeout_ms`; retry counts stay at Codex defaults (~13 s of retries vs observed
   ~85 s local tunnel outages). The patch is now a `RUN find ... sed` in
   `Dockerfile.sandbox-base` right after the npm install (marked `EXPERIMENT local-only`), which
   appends `stream_max_retries=10` / `request_max_retries=10` to the codex provider config in
   every dist bundle (the bundler duplicates the block into three files — patch by content, not
   path). The build fails loudly (`grep -q`) if the pattern ever stops matching.
9. **Editing `Dockerfile.sandbox-base` (or any image input) triggers a full image rebuild on the
   next sandbox spawn** — pay it with a cheap smoke before the run night, so runs start on a
   warm image (cold spawn ~20 min incl. the wedge above; warm spawn ~1 min).
10. **Smoke scripts must run with `PYTHONPATH=<repo root>`** — `python path/to/script.py` puts the
    script dir on `sys.path`, not the repo, and `import posthog` fails.
11. **GLM 5.3 Flash on the claude adapter works end to end** (the headline good news): Modal
    sandbox, structured JSON output, warm multi-turn session with history kept (turn 2 recall in
    10 s), effort pin `max` visible on every gateway call, priced correctly ($0.15/M in,
    $0.50/M out, $0.03/M cache read). 3-turn session ≈ $0.02.
12. **Stall watchdogs: watch ngrok traffic age, not the harness log, and skip zero timestamps.**
    The harness log goes quiet for the whole sandbox wave (a log-mtime watchdog false-alarms at any
    threshold), and ngrok's `/api/requests/http` reports in-flight requests with Go's zero time
    (`0001-01-01T00:00:00Z`) in `start` — a naive "latest request age" check computes a ~2000-year
    stall. Sample several requests, drop `year < 2020`, take the newest valid one.
13. **Validator experiments must score COVERAGE, not just precision/recall.** A weak validator can
    silently skip findings: in V2, 12 of 22 findings got no verdict at all (the validation-c2
    session died after 2 calls; two zero-token `claude-opus-4-8` rows in the usage stream are the
    session-death signature). Skipped findings count as dropped, so kept-precision looks great
    while must_fix truths vanish. Always tabulate "findings with no verdict" per run before
    reading the standard metric rows.

## Standing rules carried over from the last experiment (still true)

- NEVER write a `.py` under `products/` while a run is in flight (nodemon restarts the worker and
  fails the wave). Batch all harness edits between runs.
- ngrok can only be (re)started by the user — if the tunnels die overnight, runs stall until morning.
- Local internet is spotty; keep `MAX_CONCURRENT_SANDBOXES = 4` and the retry patch (trap 7).
- Between runs delete ONLY the PR 75215 report row, never a global wipe.
- No publish, ever, on experiment runs (`run_review` without `--publish`).
