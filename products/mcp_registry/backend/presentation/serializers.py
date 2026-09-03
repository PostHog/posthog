from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRegistryServer, MCPRegistryTool


@extend_schema_field(OpenApiTypes.OBJECT)
class JSONDictField(serializers.JSONField):
    pass


@extend_schema_field({"type": "array", "items": {"type": "object"}})
class JSONListField(serializers.JSONField):
    pass


class MCPRegistryToolSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        help_text="Tool name as advertised by the server (exec-resolved for measured servers)."
    )
    description = serializers.CharField(help_text="Tool description, from tools/list or from observed calls.")
    input_schema = JSONDictField(
        help_text="JSON Schema for the tool's input. Only populated for probed (tools_list) tools."
    )
    last_seen_at = serializers.DateTimeField(help_text="Last time this tool was observed by either source.")

    class Meta:
        model = MCPRegistryTool
        fields = ["name", "description", "input_schema", "source", "last_seen_at"]
        # `source` shadows DRF's Field.source when declared as a class attribute, so it
        # stays auto-generated (a ChoiceField from the model) and documented here.
        extra_kwargs = {
            "source": {
                "help_text": "Where we learned about this tool: a probed tools/list (authoritative schema) "
                "or MCP Analytics usage (proof of real calls, no schema).",
            },
        }


class MCPMeasuredStatsSerializer(serializers.ModelSerializer):
    window_days = serializers.IntegerField(help_text="Aggregation window in days.")
    calls = serializers.IntegerField(help_text="Tool calls observed in the window.")
    sessions = serializers.IntegerField(help_text="Distinct MCP sessions observed in the window.")
    error_rate_pct = serializers.FloatField(help_text="Errors as a percentage of calls.")
    intent_coverage_pct = serializers.FloatField(
        help_text="Percentage of calls carrying an agent-written intent ($mcp_intent)."
    )
    distinct_tools = serializers.IntegerField(help_text="Distinct effective tools called in the window.")
    harness_count = serializers.IntegerField(help_text="Distinct MCP client names observed in the window.")
    tool_stats = JSONListField(
        help_text="Per-tool usage, ordered by call volume: [{name, calls, errors, error_rate_pct}]."
    )
    link_method = serializers.CharField(
        help_text="How this measured source was attached to its registry entry "
        "(override | url | exact_name | standalone)."
    )
    link_candidates = JSONListField(
        help_text="Registry names that also matched when linking was ambiguous (kept for review)."
    )
    computed_at = serializers.DateTimeField(help_text="When this aggregate was computed.")

    class Meta:
        model = MCPMeasuredStats
        fields = [
            "window_days",
            "calls",
            "sessions",
            "errors",
            "error_rate_pct",
            "intent_coverage_pct",
            "distinct_tools",
            "harness_count",
            "tool_stats",
            "link_method",
            "link_candidates",
            "computed_at",
        ]
        # `errors` shadows Serializer.errors when declared as a class attribute, so it
        # stays auto-generated (an IntegerField from the model) and documented here.
        extra_kwargs = {
            "errors": {"help_text": "Errored tool calls in the window."},
        }


class MCPRankingScoreInfoSerializer(serializers.Serializer):
    """One ranking version's latest score for a server."""

    version = serializers.CharField(help_text="Ranking version key (see the versions endpoint).")
    score = serializers.FloatField(help_text="Static score in [0, 1]; higher ranks first.")
    components = JSONDictField(help_text="Score inputs (liveness, trust, measured signals) for explainability.")
    computed_at = serializers.DateTimeField(allow_null=True, help_text="When the run producing this score completed.")


class MCPRegistryServerListSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(help_text="Registry server id.")
    registry_name = serializers.CharField(
        help_text="Reverse-DNS name in the official MCP registry; empty for measured-only servers."
    )
    display_name = serializers.CharField(help_text="Human-readable server name.")
    description = serializers.CharField(help_text="Server description.")
    canonical_url = serializers.CharField(help_text="Primary hosted remote URL; empty for package-only servers.")
    liveness = serializers.CharField(help_text="Probed liveness state (alive_open, alive_auth, dead, ...).")
    auth_method = serializers.CharField(help_text="Detected auth method (none, oauth, api_key, unknown).")
    listed_in_registry = serializers.BooleanField(help_text="Whether the server appears in the official MCP registry.")
    is_measured = serializers.BooleanField(help_text="Whether real usage signal exists via MCP Analytics.")
    rank_score = serializers.SerializerMethodField(
        help_text="Static score under the requested ranking version; null when the version has no completed run."
    )

    class Meta:
        model = MCPRegistryServer
        fields = [
            "id",
            "registry_name",
            "display_name",
            "description",
            "canonical_url",
            "liveness",
            "auth_method",
            "listed_in_registry",
            "is_measured",
            "rank_score",
        ]

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_rank_score(self, obj: MCPRegistryServer) -> float | None:
        return getattr(obj, "rank_score", None)


class MCPRegistryServerDetailSerializer(MCPRegistryServerListSerializer):
    remotes = JSONListField(help_text="All hosted remotes: [{type, url}].")
    packages = JSONListField(help_text="Published packages: [{registry_type, identifier}].")
    repository_url = serializers.CharField(help_text="Source repository URL, when published.")
    website_url = serializers.CharField(help_text="Vendor website URL, when published.")
    last_probed_at = serializers.DateTimeField(allow_null=True, help_text="When the shallow probe last ran.")
    tools = MCPRegistryToolSerializer(many=True, help_text="Known tools, fused from probes and analytics.")
    measured_stats = MCPMeasuredStatsSerializer(
        many=True, help_text="Behavioral aggregates, one per measured MCP Analytics project."
    )
    scores = serializers.SerializerMethodField(
        help_text="Latest score under every ranking version with a completed run."
    )
    connect = serializers.SerializerMethodField(
        help_text="Connection instructions: methods ordered most-automated first, steps typed by actor "
        "(agent executes; human steps are narrated to the user)."
    )

    class Meta:
        model = MCPRegistryServer
        fields = [
            *MCPRegistryServerListSerializer.Meta.fields,
            "remotes",
            "packages",
            "repository_url",
            "website_url",
            "last_probed_at",
            "tools",
            "measured_stats",
            "scores",
            "connect",
        ]

    @extend_schema_field(MCPRankingScoreInfoSerializer(many=True))
    def get_scores(self, obj: MCPRegistryServer) -> list[dict]:
        return self.context.get("latest_scores", [])

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_connect(self, obj: MCPRegistryServer) -> dict:
        return self.context["connect_instructions"]


class MCPRankingVersionSerializer(serializers.Serializer):
    """A registered ranking version and its latest completed run."""

    version = serializers.CharField(help_text="Ranking version key, passed as ?version= to the list endpoint.")
    description = serializers.CharField(help_text="What this version scores on.")
    is_default = serializers.BooleanField(help_text="Whether this is the version used when ?version= is omitted.")
    latest_run = JSONDictField(
        allow_null=True,
        help_text="Latest completed run: {id, server_count, computed_at}; null when the version never ran.",
    )


class MCPDiscoverCandidateSerializer(serializers.Serializer):
    """One ranked candidate in a discover response, with everything an agent needs to act."""

    rank = serializers.IntegerField(help_text="1-based position under the ranking version used.")
    id = serializers.UUIDField(help_text="Registry server id, for the detail endpoint.")
    registry_name = serializers.CharField(help_text="Official registry name, empty for measured-only servers.")
    title = serializers.CharField(help_text="Human-readable server name.")
    description = serializers.CharField(help_text="What the server does.")
    score = serializers.FloatField(help_text="Rank score in [0, 1] under the ranking version used.")
    why = JSONDictField(
        help_text="Score breakdown so an agent can explain its choice: fit, liveness, trust, and whether "
        "real usage signal contributed."
    )
    liveness = serializers.CharField(help_text="Probed liveness state (alive_open, alive_auth, dead, ...).")
    auth_method = serializers.CharField(help_text="Detected auth method (none, oauth, api_key, unknown).")
    measured = JSONDictField(
        allow_null=True,
        help_text="Real MCP Analytics aggregates when the server is measured, otherwise null: calls, "
        "sessions, error_rate_pct, intent_coverage_pct, harness_count.",
    )
    matched_tools = JSONListField(
        help_text="Tools that matched the intent: [{name, description, source}]. Empty when only the server "
        "description matched."
    )
    connect = JSONDictField(
        help_text="Connection instructions, most-automated method first, steps typed by actor so the agent "
        "runs its own steps and narrates the human ones."
    )


class MCPDiscoverResponseSerializer(serializers.Serializer):
    """Everything an agent gets back from one discover call."""

    intent = serializers.CharField(help_text="The intent the candidates were ranked against, echoed back.")
    ranking_version = serializers.CharField(help_text="Ranking version the candidates were ordered by.")
    candidates = MCPDiscoverCandidateSerializer(many=True, help_text="Servers most likely to do the thing, best first.")


class MCPRegistryCompareRowSerializer(serializers.Serializer):
    """One server's position under one ranking version."""

    rank = serializers.IntegerField(help_text="1-based position under this version.")
    id = serializers.UUIDField(help_text="Registry server id.")
    registry_name = serializers.CharField(help_text="Official registry name, empty for measured-only rows.")
    display_name = serializers.CharField(help_text="Human-readable server name.")
    score = serializers.FloatField(help_text="Static score under this version.")
    is_measured = serializers.BooleanField(help_text="Whether the server carries MCP Analytics signal.")
