# MCP registry

A ranked, searchable index of MCP servers: every server in the official MCP registry, fused with
behavioral signal from MCP Analytics for the servers our customers measure. The bet: any registry
can list MCP servers; only PostHog can rank them by what agents actually did.

Backend-only for now, gated behind the `mcp-registry` feature flag.

## How the index is built

Four pipeline stages, run daily by `run_mcp_registry_sync` (flag-gated) or manually via
`python manage.py sync_mcp_registry`:

1. **Crawl** (`crawl.py`): pages through the official MCP registry API and upserts
   `MCPRegistryServer` rows. The crawl owns content fields (name, description, remotes, packages)
   and never touches operational state (probe results, measured flags).
2. **Aggregate** (`aggregation.py`): finds projects with recent `$mcp_tool_call` traffic, and per
   (project, advertised server) rolls up calls, sessions, errors, intent coverage, and per-tool
   usage into `MCPMeasuredStats`. Tool grouping uses the mcp_analytics facade's
   `EFFECTIVE_TOOL_SQL` so single-exec servers don't collapse into one `exec` bucket.
3. **Probe** (`probe.py`): a shallow, repeatable liveness probe (initialize handshake, auth
   classification from the 401 challenge, `tools/list` for open servers). Deliberately weaker than
   mcp_store's activation probe, which performs a real DCR registration and therefore can't be
   re-run; this one is side-effect-free so it can sweep the index on a schedule, stalest first.
4. **Rank** (`ranking.py`): scores every server under every registered ranking version and
   persists a run per version.

**Linking** (`linking.py`) attaches measured signal to registry entries. It is deliberately
conservative: a name like "posthog" also matches third-party repackages, so anything ambiguous
becomes a standalone row with the candidates recorded, and curated overrides
(`KNOWN_MEASURED_LINKS`) pin the known cases.

## Iterating on ranking

Ranking versions are pure functions in `ranking.py`'s `RANKING_VERSIONS`, and they are never
edited in place. To trial a change: add a new version key, let the daily sync (or
`compute_ranking_run`) score it, then compare orderings against the incumbent via
`GET .../mcp_registry/servers/compare/?versions=a,b` before promoting `DEFAULT_RANKING_VERSION`.
Scores persist per run with a component breakdown, so every ranking change stays explainable.

The current versions are the core A/B of the product thesis:

- `v1_metadata_prior`: liveness x public-metadata trust. The control arm any registry could build.
- `v2_measured_trust`: v1 plus behavioral trust (reliability weighted by volume confidence) for
  measured servers.

Query-time relevance is a token-based text match for now (`_search_filter` in
`presentation/views.py`); the seam for embedding-based capability search is that one function.

## Connection instructions

`connect.py` turns probe results into agent-executable connection instructions: methods ordered by
how hands-off they are for the human (`agent_provisioning` > `remote_open` > `cli_auth` >
`remote_oauth` > `remote_api_key` > `local_package`), each a list of steps typed by actor. An
agent runs `agent` steps itself and narrates `human` steps ("Create an API key here, then paste
it") to the user. Per-server knowledge probing can't discover lives in `connect_overrides` on the
row, seeded by `KNOWN_CONNECT_OVERRIDES`.

## Data boundaries

- Registry rows and tools are instance-global (public data plus our probes); there is no team FK.
- `MCPMeasuredStats.team_id` is provenance (which MCP Analytics project produced the aggregate),
  not access scoping.
- `measured_public` on a server defaults to False: measured stats are the server owner's analytics
  data, and showing them outside PostHog requires their opt-in. Until that flow exists the whole
  product stays internal behind the feature flag.

## Not built yet

- Embedding-based capability search (tool-level retrieval, arXiv:2511.01854) behind the existing
  `?search=` parameter.
- The agent-facing `discover` / `get_connect_config` MCP tools in `services/mcp`.
- `report_outcome` feedback ingestion (needs anti-gaming design).
- A web UI; mcp_store's marketplace is the likely surface.
