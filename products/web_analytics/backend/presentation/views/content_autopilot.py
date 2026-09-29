from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import posthog_feature_flag_enabled
from posthog.rate_limit import (
    ContentAutopilotDiscoveryBurstRateThrottle,
    ContentAutopilotDiscoverySustainedRateThrottle,
)
from posthog.security.url_validation import has_authority_bypass_chars

from products.web_analytics.backend.facade.content_autopilot import (
    MAX_PROPOSAL_MARKDOWN_CHARS,
    ContentAutopilotExportError,
    ContentAutopilotLifecycleError,
    PublicUrlFetchError,
    cancel_run,
    delete_profile,
    discover_site,
    dismiss_opportunity,
    edit_proposal,
    export_proposal,
    has_same_public_origin,
    normalize_site_origin,
    refresh_opportunities,
    regenerate_proposal,
    reject_proposal,
    start_run,
)
from products.web_analytics.backend.facade.models import (
    ContentAutopilotOpportunity,
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)

CONTENT_AUTOPILOT_FEATURE_FLAG = "web-analytics-content-autopilot"
DUPLICATE_DOMAIN_CONSTRAINT = "content_auto_profile_team_domain"
DUPLICATE_DOMAIN_MESSAGE = "This site is already configured for the project."


@contextmanager
def duplicate_domain_as_validation_error() -> Iterator[None]:
    try:
        with transaction.atomic():
            yield
    except IntegrityError as error:
        if DUPLICATE_DOMAIN_CONSTRAINT in str(error):
            raise ValidationError({"domain": DUPLICATE_DOMAIN_MESSAGE}) from error
        raise


class ContentAutopilotViewSetMixin(TeamAndOrgViewSetMixin):
    scope_object = "web_analytics"
    scope_object_read_actions = ["list", "retrieve"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        distinct_id = getattr(request.user, "distinct_id", None)
        if not distinct_id or not posthog_feature_flag_enabled(
            CONTENT_AUTOPILOT_FEATURE_FLAG, distinct_id, organization_id=self.organization_id
        ):
            raise PermissionDenied("This feature is not available.")

    def _should_skip_parents_filter(self) -> bool:
        return True

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ContentAutopilotLifecycleError | ContentAutopilotExportError):
            exc = ValidationError(str(exc))
        return super().handle_exception(exc)

    def validated_query_params(self, serializer_class: type[serializers.Serializer]) -> dict[str, Any]:
        query = serializer_class(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data


class ContentAutopilotEvidenceSerializer(serializers.Serializer):
    opportunity_kind = serializers.ChoiceField(
        choices=[
            ("poor_ctr", "Poor click-through rate"),
            ("content_gap", "Content gap"),
            ("organic_decline", "Organic decline"),
            ("ai_visibility_gap", "AI visibility gap"),
            ("site_hygiene", "Site hygiene"),
        ],
        help_text="Reason the opportunity was selected.",
    )
    explanation = serializers.CharField(help_text="Plain-language explanation of the supporting evidence.")
    page_url = serializers.URLField(required=False, allow_blank=True, help_text="Page supported by this evidence.")
    query = serializers.CharField(
        required=False, allow_blank=True, help_text="Search query supported by this evidence."
    )


class ContentAutopilotSnapshotSerializer(serializers.Serializer):
    domain = serializers.URLField(required=False, help_text="Site domain used for the run.")
    confidence = serializers.ChoiceField(
        choices=[("standard", "Standard"), ("lower", "Lower")],
        required=False,
        help_text="Confidence level based on the available data sources.",
    )
    source_urls = serializers.ListField(
        child=serializers.URLField(), required=False, help_text="Public sources authorized for this run."
    )
    content_boundaries = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Site paths authorized for this run."
    )
    brand_rules = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Editorial rules captured for this run."
    )


class ContentAutopilotErrorSerializer(serializers.Serializer):
    error_code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Error explanation suitable for the review workspace.")


class ContentAutopilotValidationCheckSerializer(serializers.Serializer):
    check_key = serializers.CharField(help_text="Stable identifier for the validation gate.")
    label = serializers.CharField(  # type: ignore[assignment]  # API field intentionally shadows DRF Field.label.
        help_text="Human-readable validation name."
    )
    passed = serializers.BooleanField(help_text="Whether the proposal passed this validation.")
    message = serializers.CharField(help_text="Validation result and any action needed.")
    blocking = serializers.BooleanField(help_text="Whether failure prevents export.")


class ContentAutopilotValidationReportSerializer(serializers.Serializer):
    passed = serializers.BooleanField(help_text="Whether every blocking validation passed.")
    checks = ContentAutopilotValidationCheckSerializer(
        many=True,
        help_text="Factual, brand, intent, originality, linking, crawlability, and schema checks.",
    )


class ContentAutopilotFrontmatterEntrySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Frontmatter field name.")
    value = serializers.CharField(help_text="Serialized frontmatter value.")


class ContentAutopilotPackageSerializer(serializers.Serializer):
    file_path = serializers.CharField(help_text="Repository-relative Markdown or MDX file path.")
    title = serializers.CharField(help_text="Content title.")
    description = serializers.CharField(help_text="Search description or summary.")
    slug = serializers.CharField(help_text="URL slug.")
    frontmatter = ContentAutopilotFrontmatterEntrySerializer(
        many=True,
        help_text="Ordered frontmatter entries.",
    )
    internal_links = serializers.ListField(
        child=serializers.URLField(),
        help_text="Validated same-origin internal links included in the content.",
    )
    source_notes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Portable source notes included with the export.",
    )


class ContentAutopilotEngineAnswerSerializer(serializers.Serializer):
    engine = serializers.CharField(help_text="Answer engine that gave the answer.")
    answer_text = serializers.CharField(help_text="The engine's most recent answer. Third-party text.")
    checked_at = serializers.CharField(help_text="When the answer was recorded, in ISO 8601.")


class ContentAutopilotCitationGapSerializer(serializers.Serializer):
    checks = serializers.IntegerField(help_text="Successful citation checks in the lookback window.")
    cited_checks = serializers.IntegerField(help_text="Checks whose answer cited the site.")
    mentioned_checks = serializers.IntegerField(
        help_text="Checks whose answer named the site's brand or cited the site.", default=0
    )
    citation_rate = serializers.FloatField(help_text="Share of checks that cited the site, from 0 to 1.")
    engines = serializers.ListField(child=serializers.CharField(), help_text="Engines that answered the prompt.")
    engines_not_citing = serializers.ListField(
        child=serializers.CharField(), help_text="Engines that never cited the site in the window."
    )
    competitor_urls = serializers.ListField(
        child=serializers.CharField(), help_text="Other sites' pages the engines cited, most frequent first."
    )
    competitor_domains = serializers.ListField(
        child=serializers.CharField(), help_text="Domains the engines cited instead, most frequent first."
    )
    engine_search_queries = serializers.ListField(
        child=serializers.CharField(), help_text="Web searches the engines ran while answering."
    )
    our_cited_urls = serializers.ListField(
        child=serializers.CharField(), help_text="Site pages the engines cited when they did cite the site."
    )
    latest_answers = ContentAutopilotEngineAnswerSerializer(many=True, help_text="Most recent answer per engine.")
    last_checked_at = serializers.CharField(help_text="When the prompt was last checked, in ISO 8601.")


class ContentAutopilotSiteProfileSerializer(serializers.ModelSerializer):
    source_urls = serializers.ListField(
        child=serializers.URLField(),
        help_text="Public sitemap and factual source URLs used to build the site profile.",
    )
    content_boundaries = serializers.ListField(
        child=serializers.CharField(),
        help_text="Same-origin URL path prefixes allowed for research.",
    )
    brand_rules = serializers.ListField(
        child=serializers.CharField(),
        help_text="Brand, terminology, and editorial rules applied to every proposal.",
    )

    class Meta:
        model = ContentAutopilotSiteProfile
        fields = [
            "id",
            "name",
            "domain",
            "source_urls",
            "content_boundaries",
            "brand_rules",
            "search_console_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Name used to identify this site in the workspace."},
            "domain": {"help_text": "Authorized site origin for this profile."},
            "search_console_enabled": {"help_text": "Whether to use connected Google Search Console data."},
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        def submitted(field: str, default: Any = "") -> Any:
            return attrs[field] if field in attrs else getattr(self.instance, field, default)

        try:
            domain = normalize_site_origin(submitted("domain"))
        except ValueError as error:
            raise ValidationError({"domain": str(error)}) from error

        attrs["domain"] = domain
        attrs["name"] = submitted("name").strip() or (urlparse(domain).hostname or domain).removeprefix("www.")

        for source_url in submitted("source_urls", []) or []:
            url = str(source_url)
            parsed_source = urlparse(url)
            if (
                parsed_source.fragment
                or parsed_source.path.startswith("//")
                or has_authority_bypass_chars(url)
                or not has_same_public_origin(url, domain)
            ):
                raise ValidationError(
                    {"source_urls": "Use public same-origin source URLs without credentials or fragments."}
                )

        for boundary in submitted("content_boundaries", []) or []:
            path = str(boundary)
            if (
                not path.startswith("/")
                or path.startswith("//")
                or ".." in path.split("/")
                or any(character in path for character in "\\?#")
            ):
                raise ValidationError({"content_boundaries": "Use same-origin path prefixes beginning with '/'."})

        return attrs

    def create(self, validated_data: dict[str, Any]) -> ContentAutopilotSiteProfile:
        team = self.context["get_team"]()
        user_id = getattr(self.context["request"].user, "id", None)
        with duplicate_domain_as_validation_error():
            return ContentAutopilotSiteProfile.objects.for_team(team.id).create(
                team=team,
                created_by_id=user_id,
                updated_by_id=user_id,
                **validated_data,
            )

    def update(
        self, instance: ContentAutopilotSiteProfile, validated_data: dict[str, Any]
    ) -> ContentAutopilotSiteProfile:
        instance.updated_by_id = getattr(self.context["request"].user, "id", None)
        with duplicate_domain_as_validation_error():
            return super().update(instance, validated_data)


class ContentAutopilotSiteDiscoveryRequestSerializer(serializers.Serializer):
    domain = serializers.URLField(help_text="Public site URL to inspect for onboarding defaults.")


class ContentAutopilotSiteDiscoveryResponseSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Site name inferred from the homepage or hostname.")
    domain = serializers.URLField(help_text="Normalized site origin.")
    source_urls = serializers.ListField(
        child=serializers.URLField(), help_text="Detected sitemap URLs or an editable conventional suggestion."
    )
    content_boundaries = serializers.ListField(
        child=serializers.CharField(), help_text="Editable same-origin path boundaries."
    )
    sitemap_detected = serializers.BooleanField(help_text="Whether at least one sitemap was verified.")
    warnings = serializers.ListField(child=serializers.CharField(), help_text="Non-blocking discovery warnings.")


class ContentAutopilotRunStartRequestSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField(help_text="Site profile to research.")


class ContentAutopilotRunListQuerySerializer(serializers.Serializer):
    profile_id = serializers.UUIDField(required=False, help_text="Only return runs for this site profile.")


class ContentAutopilotRunSerializer(serializers.ModelSerializer):
    input_snapshot = ContentAutopilotSnapshotSerializer(help_text="Immutable inputs captured at run start.")
    errors = ContentAutopilotErrorSerializer(  # type: ignore[assignment]  # API field intentionally shadows Serializer.errors.
        many=True, help_text="Inspectable workflow errors from this run."
    )

    class Meta:
        model = ContentAutopilotRun
        fields = [
            "id",
            "profile_id",
            "run_status",
            "input_snapshot",
            "errors",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "profile_id": {"help_text": "Site profile used by this run."},
            "run_status": {"help_text": "Current durable workflow status."},
        }


class ContentAutopilotProposalBaseSerializer(serializers.ModelSerializer):
    evidence = ContentAutopilotEvidenceSerializer(many=True, help_text="Performance evidence for this proposal.")
    validation_report = ContentAutopilotValidationReportSerializer(
        help_text="Blocking and advisory validation results."
    )


class ContentAutopilotProposalSerializer(ContentAutopilotProposalBaseSerializer):
    content_package = ContentAutopilotPackageSerializer(
        help_text="Structured package that accompanies the exported Markdown."
    )

    class Meta:
        model = ContentAutopilotProposal
        fields = [
            "id",
            "run_id",
            "proposal_type",
            "lifecycle_status",
            "title",
            "target_query",
            "target_url",
            "evidence",
            "validation_report",
            "content_package",
            "original_markdown",
            "proposed_markdown",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "run_id": {"help_text": "Run that generated this proposal."},
            "proposal_type": {"help_text": "New article or bounded page improvement."},
            "lifecycle_status": {"help_text": "Review and export lifecycle status."},
            "title": {"help_text": "Review title for this proposal."},
            "target_query": {"help_text": "Primary query or topic targeted by this proposal."},
            "target_url": {"help_text": "Existing or intended public URL."},
            "original_markdown": {"help_text": "Existing content for page-improvement diffs."},
            "proposed_markdown": {"help_text": "Full proposed Markdown after edits."},
        }


class ContentAutopilotProposalListSerializer(ContentAutopilotProposalBaseSerializer):
    file_path = serializers.SerializerMethodField(help_text="Repository-relative export path.")

    class Meta:
        model = ContentAutopilotProposal
        fields = [
            "id",
            "run_id",
            "proposal_type",
            "lifecycle_status",
            "title",
            "target_query",
            "evidence",
            "validation_report",
            "file_path",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField)
    def get_file_path(self, proposal: ContentAutopilotProposal) -> str:
        return proposal.content_package.get("file_path", "")


class ContentAutopilotProposalListQuerySerializer(serializers.Serializer):
    run_id = serializers.UUIDField(required=False, help_text="Only return proposals from this content run.")
    profile_id = serializers.UUIDField(required=False, help_text="Only return proposals for this site profile.")


class ContentAutopilotProposalEditRequestSerializer(serializers.Serializer):
    proposed_markdown = serializers.CharField(
        max_length=MAX_PROPOSAL_MARKDOWN_CHARS,
        trim_whitespace=False,
        help_text="Edited Markdown to save for review.",
    )
    content_package = ContentAutopilotPackageSerializer(
        help_text="Updated structured package to save with the proposal."
    )


class ContentAutopilotExportResponseSerializer(serializers.Serializer):
    filename = serializers.CharField(help_text="Suggested export filename.")
    markdown = serializers.CharField(help_text="Validated Markdown content.")
    content_package = ContentAutopilotPackageSerializer(help_text="Structured JSON package for a CMS adapter.")


class ContentAutopilotOpportunitySerializer(serializers.ModelSerializer):
    evidence = ContentAutopilotEvidenceSerializer(many=True, help_text="Why this opportunity was selected.")
    gap = ContentAutopilotCitationGapSerializer(help_text="Citation check results behind this opportunity.")

    class Meta:
        model = ContentAutopilotOpportunity
        fields = [
            "id",
            "profile_id",
            "run_id",
            "proposal_id",
            "kind",
            "title",
            "score",
            "recommended_type",
            "target_url",
            "evidence",
            "gap",
            "status",
            "last_refreshed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "profile_id": {"help_text": "Site profile this opportunity belongs to."},
            "run_id": {"help_text": "Latest run that drafted this opportunity."},
            "proposal_id": {"help_text": "Latest proposal drafted for this opportunity."},
            "kind": {"help_text": "Type of visibility gap."},
            "title": {"help_text": "The prompt the site isn't cited for."},
            "score": {"help_text": "Priority from 0 to 1. Higher means a clearer, more consistent gap."},
            "recommended_type": {
                "help_text": "`page_improvement` when the engines cited a site page for the prompt. Otherwise `new_content`, and drafting decides between a new page and an existing one."
            },
            "target_url": {
                "help_text": "Site page the engines cited for the prompt, to improve. Empty when no page was cited."
            },
            "status": {"help_text": "Where the opportunity is in the drafting workflow."},
            "last_refreshed_at": {"help_text": "When the citation data was last read."},
        }


class ContentAutopilotOpportunityListQuerySerializer(serializers.Serializer):
    profile_id = serializers.UUIDField(help_text="Site profile to list opportunities for.")


class ContentAutopilotOpportunityRefreshRequestSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField(help_text="Site profile to refresh opportunities for.")


class ContentAutopilotSiteProfileViewSet(ContentAutopilotViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ContentAutopilotSiteProfileSerializer
    queryset = ContentAutopilotSiteProfile.objects.unscoped()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "discover":
            return [
                ContentAutopilotDiscoveryBurstRateThrottle(),
                ContentAutopilotDiscoverySustainedRateThrottle(),
            ]
        return super().get_throttles()

    def safely_get_queryset(
        self, queryset: QuerySet[ContentAutopilotSiteProfile]
    ) -> QuerySet[ContentAutopilotSiteProfile]:
        return ContentAutopilotSiteProfile.objects.for_team(self.team_id).filter(deleted=False).order_by("created_at")

    def perform_destroy(self, instance: ContentAutopilotSiteProfile) -> None:
        delete_profile(team=self.team, profile_id=str(instance.id))

    @validated_request(
        request_serializer=ContentAutopilotSiteDiscoveryRequestSerializer,
        operation_id="web_analytics_content_autopilot_profiles_discover",
        summary="Discover content autopilot site settings",
        description="Inspects a public site for its canonical origin, name, and sitemap URLs.",
        responses={200: OpenApiResponse(response=ContentAutopilotSiteDiscoveryResponseSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], required_scopes=["web_analytics:write"])
    def discover(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        try:
            result = discover_site(request.validated_data["domain"])
        except (ValueError, PublicUrlFetchError) as error:
            raise ValidationError({"domain": str(error)}) from error
        return Response(ContentAutopilotSiteDiscoveryResponseSerializer(instance=result).data)


@extend_schema_view(list=extend_schema(parameters=[ContentAutopilotRunListQuerySerializer]))
class ContentAutopilotRunViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotRunSerializer
    queryset = ContentAutopilotRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[ContentAutopilotRun]) -> QuerySet[ContentAutopilotRun]:
        queryset = ContentAutopilotRun.objects.for_team(self.team_id).filter(profile__deleted=False)
        if self.action == "list":
            filters = self.validated_query_params(ContentAutopilotRunListQuerySerializer)
            if profile_id := filters.get("profile_id"):
                queryset = queryset.filter(profile_id=profile_id)
        return queryset.order_by("-created_at")

    @validated_request(
        request_serializer=ContentAutopilotRunStartRequestSerializer,
        operation_id="web_analytics_content_autopilot_runs_start",
        summary="Start a content autopilot run",
        description="Captures the current profile and creates one pending on-demand content research run.",
        responses={202: OpenApiResponse(response=ContentAutopilotRunSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], required_scopes=["web_analytics:write"])
    def start(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        run = start_run(
            team=self.team,
            profile_id=str(request.validated_data["profile_id"]),
            triggered_by_id=getattr(request.user, "id", None),
        )
        return Response(self.get_serializer(run).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        operation_id="web_analytics_content_autopilot_runs_cancel",
        summary="Cancel a content autopilot run",
        description="Stops a pending or generating run without creating content writes.",
        responses={200: OpenApiResponse(response=ContentAutopilotRunSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def cancel(self, request: Request, **kwargs: Any) -> Response:
        run = cancel_run(team=self.team, run_id=str(self.get_object().id))
        return Response(self.get_serializer(run).data)


@extend_schema_view(
    list=extend_schema(
        parameters=[ContentAutopilotProposalListQuerySerializer],
        responses=ContentAutopilotProposalListSerializer(many=True),
    )
)
class ContentAutopilotProposalViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotProposalSerializer
    queryset = ContentAutopilotProposal.objects.unscoped()

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        if self.action == "list":
            return ContentAutopilotProposalListSerializer
        return ContentAutopilotProposalSerializer

    def safely_get_queryset(self, queryset: QuerySet[ContentAutopilotProposal]) -> QuerySet[ContentAutopilotProposal]:
        queryset = ContentAutopilotProposal.objects.for_team(self.team_id).filter(run__profile__deleted=False)
        if self.action == "list":
            filters = self.validated_query_params(ContentAutopilotProposalListQuerySerializer)
            if run_id := filters.get("run_id"):
                queryset = queryset.filter(run_id=run_id)
            if profile_id := filters.get("profile_id"):
                queryset = queryset.filter(run__profile_id=profile_id)
            queryset = queryset.defer("original_markdown", "proposed_markdown", "brief", "source_ledger", "research")
        return queryset.order_by("-created_at")

    @validated_request(
        request_serializer=ContentAutopilotProposalEditRequestSerializer,
        operation_id="web_analytics_content_autopilot_proposals_edit",
        summary="Edit a content proposal",
        description="Saves reviewed Markdown and its structured package without publishing it.",
        responses={200: OpenApiResponse(response=ContentAutopilotProposalSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def edit(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        proposal = edit_proposal(team=self.team, proposal_id=str(self.get_object().id), **request.validated_data)
        return Response(self.get_serializer(proposal).data)

    @validated_request(
        operation_id="web_analytics_content_autopilot_proposals_reject",
        summary="Reject a content proposal",
        description="Rejects a proposal without changing the public site.",
        responses={200: OpenApiResponse(response=ContentAutopilotProposalSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def reject(self, request: Request, **kwargs: Any) -> Response:
        proposal = reject_proposal(team=self.team, proposal_id=str(self.get_object().id))
        return Response(self.get_serializer(proposal).data)

    @validated_request(
        operation_id="web_analytics_content_autopilot_proposals_regenerate",
        summary="Regenerate a content proposal",
        description="Returns a proposal to generation while keeping its previous result inspectable in history.",
        responses={202: OpenApiResponse(response=ContentAutopilotProposalSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def regenerate(self, request: Request, **kwargs: Any) -> Response:
        proposal = regenerate_proposal(team=self.team, proposal_id=str(self.get_object().id))
        return Response(self.get_serializer(proposal).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        operation_id="web_analytics_content_autopilot_proposals_export",
        summary="Export a content proposal",
        description="Returns validated Markdown and structured JSON without publishing it.",
        responses={200: OpenApiResponse(response=ContentAutopilotExportResponseSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def export(self, request: Request, **kwargs: Any) -> Response:
        exported = export_proposal(team=self.team, proposal_id=str(self.get_object().id))
        return Response(ContentAutopilotExportResponseSerializer(instance=exported).data)


@extend_schema_view(list=extend_schema(parameters=[ContentAutopilotOpportunityListQuerySerializer]))
class ContentAutopilotOpportunityViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotOpportunitySerializer
    queryset = ContentAutopilotOpportunity.objects.unscoped()

    def safely_get_queryset(
        self, queryset: QuerySet[ContentAutopilotOpportunity]
    ) -> QuerySet[ContentAutopilotOpportunity]:
        queryset = ContentAutopilotOpportunity.objects.for_team(self.team_id).filter(profile__deleted=False)
        if self.action == "list":
            filters = self.validated_query_params(ContentAutopilotOpportunityListQuerySerializer)
            queryset = queryset.filter(profile_id=filters["profile_id"])
        return queryset.order_by("-score", "title")

    @validated_request(
        request_serializer=ContentAutopilotOpportunityRefreshRequestSerializer,
        operation_id="web_analytics_content_autopilot_opportunities_refresh",
        summary="Refresh content opportunities",
        description="Re-reads AI citation checks and updates the site's content opportunities. Makes no model calls.",
        responses={200: OpenApiResponse(response=ContentAutopilotOpportunitySerializer(many=True))},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], required_scopes=["web_analytics:write"], pagination_class=None)
    def refresh(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        profile_id = str(request.validated_data["profile_id"])
        refresh_opportunities(team=self.team, profile_id=profile_id)
        opportunities = (
            ContentAutopilotOpportunity.objects.for_team(self.team_id)
            .filter(profile_id=profile_id, profile__deleted=False)
            .order_by("-score", "title")
        )
        return Response(self.get_serializer(opportunities, many=True).data)

    @validated_request(
        operation_id="web_analytics_content_autopilot_opportunities_dismiss",
        summary="Dismiss a content opportunity",
        description="Hides an opportunity from the list until its citation data changes.",
        responses={200: OpenApiResponse(response=ContentAutopilotOpportunitySerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def dismiss(self, request: Request, **kwargs: Any) -> Response:
        opportunity = self.get_object()
        dismiss_opportunity(team=self.team, opportunity_id=str(opportunity.id))
        opportunity.refresh_from_db()
        return Response(self.get_serializer(opportunity).data)
