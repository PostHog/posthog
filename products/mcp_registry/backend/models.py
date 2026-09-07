from django.db import models
from django.db.models import Q

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel

# Liveness as classified by the shallow probe. `package_only` and `unprobed` are
# pre-probe states derived from the registry entry itself.
LIVENESS_CHOICES = [
    ("alive_open", "Alive, no auth required"),
    ("alive_auth", "Alive, behind auth"),
    ("alive_protocol", "Alive, protocol-level error"),
    ("dead", "Dead"),
    ("not_mcp", "Responds, but not an MCP server"),
    ("package_only", "No hosted remote, package install only"),
    ("unprobed", "Not probed yet"),
]

# How the server authenticates, as far as we can tell without credentials.
# `oauth` comes from a Bearer WWW-Authenticate challenge, `api_key` from an
# explicit api-key hint in the 401/403 body or headers.
AUTH_METHOD_CHOICES = [
    ("none", "No auth"),
    ("oauth", "OAuth"),
    ("api_key", "API key"),
    ("unknown", "Unknown"),
]

TOOL_SOURCE_CHOICES = [
    ("tools_list", "Probed tools/list"),
    ("analytics", "MCP Analytics usage"),
]

# How a measured (team, server_name) signal got attached to its registry server row.
LINK_METHOD_CHOICES = [
    ("override", "Known-link override"),
    ("url", "Remote URL match"),
    ("exact_name", "Exact name match"),
    ("standalone", "No registry match, standalone row"),
]

RANKING_RUN_STATUS_CHOICES = [
    ("running", "Running"),
    ("completed", "Completed"),
    ("failed", "Failed"),
]


class MCPRegistryServer(UUIDModel):
    """One MCP server known to the registry index.

    Global rows (no team FK): the index fuses public data (the official MCP registry
    crawl, probes) with cross-team aggregates from MCP Analytics. A row can come from
    either side alone or both; `listed_in_registry` / `is_measured` record provenance.
    """

    # Reverse-DNS name from the official registry (e.g. "io.github.PostHog/mcp").
    # Empty for measured-only servers that never appeared in the registry.
    registry_name = models.CharField(max_length=400, blank=True, default="")
    display_name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    # Primary streamable-http remote, when the server is hosted.
    canonical_url = models.URLField(max_length=2048, blank=True, default="")
    remotes = models.JSONField(default=list, blank=True)
    packages = models.JSONField(default=list, blank=True)
    repository_url = models.URLField(max_length=2048, blank=True, default="")
    website_url = models.URLField(max_length=2048, blank=True, default="")

    listed_in_registry = models.BooleanField(default=False)
    # Raw official-registry metadata (version, publishedAt, updatedAt, status).
    registry_meta = models.JSONField(default=dict, blank=True)
    is_measured = models.BooleanField(default=False)
    # Whether measured stats may be shown outside PostHog. Stays False until the
    # server owner opts in, because it is their analytics data.
    measured_public = models.BooleanField(default=False)

    liveness = models.CharField(max_length=20, choices=LIVENESS_CHOICES, default="unprobed")
    auth_method = models.CharField(max_length=20, choices=AUTH_METHOD_CHOICES, default="unknown")
    last_probed_at = models.DateTimeField(null=True, blank=True)
    probe_detail = models.CharField(max_length=200, blank=True, default="")

    # Soft link to a curated mcp_store MCPServerTemplate (UUID, no FK: mcp_store is a
    # separate product boundary and the link is advisory).
    mcp_store_template_id = models.UUIDField(null=True, blank=True)

    # Per-server overrides for connection instructions (see connect.py for the shape).
    connect_overrides = models.JSONField(default=dict, blank=True)
    # The vendor exposes an API through which an agent can provision an account/key
    # without a human. When True, connect instructions always prefer that path.
    supports_agent_provisioning = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_registry_server"
        constraints = [
            models.UniqueConstraint(
                fields=["registry_name"],
                condition=~Q(registry_name=""),
                name="unique_registry_name_when_set",
            ),
        ]
        indexes = [
            models.Index(fields=["listed_in_registry"]),
            models.Index(fields=["is_measured"]),
            models.Index(fields=["liveness"]),
            models.Index(fields=["last_probed_at"]),
            models.Index(fields=["canonical_url"]),
        ]

    def __str__(self) -> str:
        return self.registry_name or self.display_name


class MCPRegistryTool(UUIDModel):
    """One tool a server exposes, from a probed tools/list or from analytics usage.

    A tools/list row is authoritative for schema; an analytics row proves real usage
    (and is the only source for auth-walled servers). The same tool name upgrades in
    place when a better source arrives.
    """

    server = models.ForeignKey(MCPRegistryServer, on_delete=models.CASCADE, related_name="tools")
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    input_schema = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=20, choices=TOOL_SOURCE_CHOICES)
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_registry_tool"
        constraints = [
            models.UniqueConstraint(fields=["server", "name"], name="unique_tool_per_server"),
        ]

    def __str__(self) -> str:
        return f"{self.server}:{self.name}"


class MCPMeasuredStats(UUIDModel):
    """Behavioral aggregate for one measured server, from one MCP Analytics project.

    Keyed on (team_id, server_name): the same advertised server name can appear in
    more than one customer project, and each is its own signal source. `team_id` is a
    raw int on purpose, because this is a global table and must not FK the hot team table.

    `objects` is the fail-closed TeamScopedManager: a bare `.objects` query without team
    context raises rather than leaking another project's measurements, so the IDOR
    coverage check needs no exemption for this model. Reads that intentionally span the
    fleet (the staff rollup, ranking) opt out with `.unscoped()`; reads for one project's
    own measurements go through `.for_team(...)` or the request's ambient team scope.
    """

    objects = TeamScopedManager()
    # Django framework internals (related-object access, prefetch_related, admin) use
    # `_default_manager` and expect an unfiltered manager; pointing that at `all_teams`
    # keeps `server.measured_stats.all()` working while `.objects` stays fail-closed.
    all_teams = models.Manager()  # noqa: DJ012

    server = models.ForeignKey(MCPRegistryServer, on_delete=models.CASCADE, related_name="measured_stats")
    team_id = models.IntegerField()
    server_name = models.CharField(max_length=400)
    window_days = models.IntegerField()

    calls = models.BigIntegerField(default=0)
    sessions = models.BigIntegerField(default=0)
    errors = models.BigIntegerField(default=0)
    error_rate_pct = models.FloatField(default=0.0)
    intent_coverage_pct = models.FloatField(default=0.0)
    distinct_tools = models.IntegerField(default=0)
    harness_count = models.IntegerField(default=0)
    # Top tools by call volume: [{"name", "calls", "errors", "error_rate_pct"}].
    tool_stats = models.JSONField(default=list, blank=True)

    link_method = models.CharField(max_length=20, choices=LINK_METHOD_CHOICES)
    # Registry names that also matched when linking was ambiguous, kept for review.
    link_candidates = models.JSONField(default=list, blank=True)

    computed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_registry_measured_stats"
        verbose_name_plural = "MCP measured stats"
        # Related-object access (server.measured_stats.all(), prefetch_related) resolves
        # through `_default_manager`; point it at the unscoped sibling so those reads keep
        # working without team context while `.objects` stays fail-closed.
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team_id", "server_name"], name="unique_measured_source"),
        ]
        indexes = [
            models.Index(fields=["server"]),
        ]

    def __str__(self) -> str:
        return f"{self.server_name} (team {self.team_id})"


class MCPRankingRun(UUIDModel):
    """One execution of one ranking version over the whole index.

    Scores are persisted per run rather than overwritten in place so ranking versions
    can be iterated on and compared side by side: run v1 and v2 against the same index
    state, then diff their orderings before promoting either.
    """

    version = models.CharField(max_length=100)
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=RANKING_RUN_STATUS_CHOICES, default="running")
    error = models.TextField(blank=True, default="")
    server_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_registry_ranking_run"
        indexes = [
            models.Index(fields=["version", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.version} @ {self.created_at:%Y-%m-%d %H:%M}"


class MCPRankingScore(UUIDModel):
    """The static (query-independent) score one run assigned one server.

    Search combines this with query-time relevance; this row is the "authority" half,
    with `components` recording every input so ranking changes stay explainable.
    """

    run = models.ForeignKey(MCPRankingRun, on_delete=models.CASCADE, related_name="scores")
    server = models.ForeignKey(MCPRegistryServer, on_delete=models.CASCADE, related_name="scores")
    score = models.FloatField()
    components = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "mcp_registry_ranking_score"
        constraints = [
            models.UniqueConstraint(fields=["run", "server"], name="unique_score_per_run_server"),
        ]
        indexes = [
            models.Index(fields=["run", "-score"]),
        ]

    def __str__(self) -> str:
        return f"{self.server} = {self.score:.4f}"
