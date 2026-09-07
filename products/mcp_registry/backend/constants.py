# Deployment-level kill switch for the sync/ranking pipeline (crawl, aggregate, probe, rank)
# and gate for the DRF endpoints. Evaluated with a constant distinct_id for the pipeline
# (whole-deployment toggle, like mcp-analytics-clustering-schedule) and per-user for the API.
MCP_REGISTRY_FEATURE_FLAG = "mcp-registry"
MCP_REGISTRY_PIPELINE_DISTINCT_ID = "internal_mcp_registry_pipeline"

OFFICIAL_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0/servers"
# The registry has ~22k active servers at ~100/page; this cap only guards against a
# pagination bug or a runaway registry, not normal growth.
OFFICIAL_REGISTRY_MAX_PAGES = 1_000

# How far back the measured-signal aggregation looks, and the window stamped on stats rows.
MEASURED_WINDOW_DAYS = 30
# A stats row stops counting toward trust once it is this old. Aggregation only upserts
# servers that appeared in the window, so a server that stopped being called keeps its
# last row forever; without this it would keep the trust it earned when it was busy.
MEASURED_STALE_AFTER_DAYS = 60
# Per-server cap on tool rows kept from analytics aggregation (ordered by call volume).
MEASURED_TOOL_LIMIT = 200
# Cap on teams pulled into one aggregation run; revisit before wide rollout.
MEASURED_TEAM_LIMIT = 500

# Shallow-probe batch size per scheduled run: stalest servers first, so the whole index
# converges over successive days without one giant sweep.
PROBE_BATCH_SIZE = 500
PROBE_TIMEOUT_SECONDS = 10
PROBE_TOOL_LIMIT = 100
PROBE_TOOL_DESCRIPTION_MAX_CHARS = 500
