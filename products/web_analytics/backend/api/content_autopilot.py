import re
from typing import Any
from urllib.parse import urlparse

from django.db.models import QuerySet

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.web_analytics.backend.content_autopilot.delivery import (
    ContentAutopilotDeliveryError,
    export_proposal,
    open_pull_request,
)
from products.web_analytics.backend.content_autopilot.lifecycle import (
    ContentAutopilotLifecycleError,
    cancel_run,
    edit_proposal,
    regenerate_proposal,
    reject_proposal,
    start_run,
)
from products.web_analytics.backend.content_autopilot.site_discovery import discover_site, normalize_site_origin
from products.web_analytics.backend.models import (
    ContentAutopilotMeasurement,
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)

CONTENT_AUTOPILOT_FEATURE_FLAGS = (
    "web-analytics-page-performance",
    "web-analytics-content-autopilot",
)


class ContentAutopilotViewSetMixin(TeamAndOrgViewSetMixin):
    scope_object = "web_analytics"
    scope_object_read_actions = ["list", "retrieve"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        distinct_id = getattr(request.user, "distinct_id", None)
        organization_id = str(self.organization.id)
        flag_results = (
            [
                posthoganalytics.feature_enabled(
                    flag,
                    distinct_id,
                    groups={"organization": organization_id},
                    group_properties={"organization": {"id": organization_id}},
                )
                for flag in CONTENT_AUTOPILOT_FEATURE_FLAGS
            ]
            if distinct_id
            else []
        )
        if len(flag_results) != len(CONTENT_AUTOPILOT_FEATURE_FLAGS) or not all(flag_results):
            raise PermissionDenied("This feature is not available.")


class ContentAutopilotMetricSerializer(serializers.Serializer):
    impressions = serializers.IntegerField(required=False, help_text="Google Search impressions in the period.")
    clicks = serializers.IntegerField(required=False, help_text="Google Search clicks in the period.")
    click_through_rate = serializers.FloatField(required=False, help_text="Google Search click-through rate.")
    average_position = serializers.FloatField(required=False, help_text="Average Google Search position.")
    visitors = serializers.IntegerField(required=False, help_text="PostHog visitors in the period.")
    ai_referrals = serializers.IntegerField(required=False, help_text="Visits referred by AI assistants.")
    crawler_requests = serializers.IntegerField(required=False, help_text="Requests from recognized AI crawlers.")
    engagement_rate = serializers.FloatField(required=False, help_text="Engaged visitors divided by visitors.")
    conversions = serializers.IntegerField(required=False, help_text="Configured conversions in the period.")


class ContentAutopilotSnapshotSerializer(serializers.Serializer):
    captured_at = serializers.DateTimeField(required=False, help_text="When the run inputs were captured.")
    domain = serializers.URLField(required=False, help_text="Site domain used for the run.")
    search_console_connected = serializers.BooleanField(
        required=False, help_text="Whether Search Console data was available."
    )
    confidence = serializers.ChoiceField(
        choices=[("standard", "Standard"), ("lower", "Lower")],
        required=False,
        help_text="Confidence level based on the available data sources.",
    )


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
    metrics = ContentAutopilotMetricSerializer(
        required=False,
        help_text="Observed metrics supporting the opportunity.",
    )


class ContentAutopilotErrorSerializer(serializers.Serializer):
    error_code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Error explanation suitable for the review workspace.")
    retryable = serializers.BooleanField(help_text="Whether the failed step can be retried.")


class ContentAutopilotSourceSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Public source URL used for factual claims.")
    title = serializers.CharField(help_text="Source page title.")
    supported_claims = serializers.ListField(
        child=serializers.CharField(),
        help_text="Claims in the proposal supported by this source.",
    )


class ContentAutopilotValidationCheckSerializer(serializers.Serializer):
    check_key = serializers.CharField(help_text="Stable identifier for the validation gate.")
    label = serializers.CharField(  # type: ignore[assignment]  # API field intentionally shadows DRF Field.label.
        help_text="Human-readable validation name."
    )
    passed = serializers.BooleanField(help_text="Whether the proposal passed this validation.")
    message = serializers.CharField(help_text="Validation result and any action needed.")
    blocking = serializers.BooleanField(help_text="Whether failure prevents delivery.")


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
    markdown = serializers.CharField(help_text="Validated Markdown body.")
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
    content_directories = serializers.ListField(
        child=serializers.CharField(),
        help_text="Repository directories where approved content may be written.",
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
            "delivery_mode",
            "github_repository",
            "base_branch",
            "content_directories",
            "url_to_file_convention",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Name used to identify this site in the workspace."},
            "domain": {"help_text": "Authorized site origin for this profile."},
            "search_console_enabled": {"help_text": "Whether to use connected Google Search Console data."},
            "delivery_mode": {"help_text": "Deliver approved work as exports or GitHub pull requests."},
            "github_repository": {"help_text": "GitHub repository in owner/name format."},
            "base_branch": {"help_text": "Base branch for content pull requests."},
            "url_to_file_convention": {"help_text": "Rule mapping public URLs to repository file paths."},
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        values = {**getattr(self.instance, "__dict__", {}), **attrs}
        try:
            domain = normalize_site_origin(str(values.get("domain") or ""))
        except ValueError as error:
            raise ValidationError({"domain": str(error)}) from error
        parsed_domain = urlparse(domain)
        if parsed_domain.username or parsed_domain.password or parsed_domain.query or parsed_domain.fragment:
            raise ValidationError({"domain": "Enter a public site origin without credentials, query, or fragment."})
        if parsed_domain.path not in {"", "/"}:
            raise ValidationError({"domain": "Enter the site origin without a content path."})

        attrs["domain"] = domain
        name = str(values.get("name") or "").strip()
        attrs["name"] = name or (parsed_domain.hostname or domain).removeprefix("www.")
        matching_profiles = ContentAutopilotSiteProfile.objects.for_team(self.context["get_team"]().id).filter(
            domain=domain
        )
        if self.instance is not None:
            matching_profiles = matching_profiles.exclude(id=self.instance.id)
        if matching_profiles.exists():
            raise ValidationError({"domain": "This site is already configured for the project."})

        for source_url in values.get("source_urls") or []:
            parsed_source = urlparse(str(source_url))
            if (
                parsed_source.username
                or parsed_source.password
                or parsed_source.query
                or parsed_source.fragment
                or parsed_source.path.startswith("//")
                or "\\" in parsed_source.path
                or parsed_source.scheme.lower() != parsed_domain.scheme.lower()
                or parsed_source.netloc.lower() != parsed_domain.netloc.lower()
            ):
                raise ValidationError(
                    {"source_urls": "Use public same-origin source URLs without credentials, queries, or fragments."}
                )

        boundaries = values.get("content_boundaries") or []
        if any(
            not str(boundary).startswith("/")
            or str(boundary).startswith("//")
            or ".." in str(boundary).split("/")
            or "\\" in str(boundary)
            or "?" in str(boundary)
            or "#" in str(boundary)
            for boundary in boundaries
        ):
            raise ValidationError({"content_boundaries": "Use same-origin path prefixes beginning with '/'."})

        delivery_mode = values.get("delivery_mode")
        repository = str(values.get("github_repository") or "")
        directories = values.get("content_directories") or []
        if delivery_mode == ContentAutopilotSiteProfile.DeliveryMode.GITHUB:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                raise ValidationError({"github_repository": "Enter a GitHub repository in owner/name format."})
            if not directories:
                raise ValidationError({"content_directories": "Add at least one repository content directory."})
        if any(
            not path or path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
            for path in directories
        ):
            raise ValidationError({"content_directories": "Use repository-relative directories without '..'."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ContentAutopilotSiteProfile:
        team = self.context["get_team"]()
        user_id = getattr(self.context["request"].user, "id", None)
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
    selected_opportunities = ContentAutopilotEvidenceSerializer(
        many=True,
        help_text="Ranked opportunities selected for generation.",
    )
    errors = ContentAutopilotErrorSerializer(  # type: ignore[assignment]  # API field intentionally shadows Serializer.errors.
        many=True, help_text="Inspectable workflow errors and retryability."
    )

    class Meta:
        model = ContentAutopilotRun
        fields = [
            "id",
            "profile_id",
            "run_status",
            "input_snapshot",
            "selected_opportunities",
            "errors",
            "workflow_id",
            "triggered_by_id",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "profile_id": {"help_text": "Site profile used by this run."},
            "run_status": {"help_text": "Current durable workflow status."},
            "workflow_id": {"help_text": "Temporal workflow identifier for this run."},
            "triggered_by_id": {"help_text": "User who explicitly started this run."},
        }


class ContentAutopilotGenerationHistoryEntrySerializer(serializers.Serializer):
    archived_at = serializers.DateTimeField(help_text="When this generation attempt was archived.")
    lifecycle_status = serializers.ChoiceField(
        choices=ContentAutopilotProposal.LifecycleStatus.choices,
        help_text="Proposal state when this attempt was archived.",
    )
    proposed_markdown = serializers.CharField(help_text="Markdown produced by this generation attempt.")
    content_package = ContentAutopilotPackageSerializer(help_text="Delivery package produced by this attempt.")
    source_ledger = ContentAutopilotSourceSerializer(many=True, help_text="Sources used by this attempt.")
    validation_report = ContentAutopilotValidationReportSerializer(help_text="Validation result for this attempt.")


class ContentAutopilotProposalSerializer(serializers.ModelSerializer):
    evidence = ContentAutopilotEvidenceSerializer(many=True, help_text="Performance evidence for this proposal.")
    source_ledger = ContentAutopilotSourceSerializer(
        many=True,
        help_text="Public sources supporting factual claims.",
    )
    validation_report = ContentAutopilotValidationReportSerializer(
        help_text="Blocking and advisory validation results."
    )
    content_package = ContentAutopilotPackageSerializer(help_text="Canonical package used by every delivery adapter.")
    generation_history = ContentAutopilotGenerationHistoryEntrySerializer(
        many=True,
        help_text="Previous generation attempts retained for review.",
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
            "audience",
            "search_intent",
            "expected_outcome",
            "evidence",
            "source_ledger",
            "validation_report",
            "generation_history",
            "content_package",
            "original_markdown",
            "proposed_markdown",
            "delivery_state",
            "delivery_reference",
            "pull_request_url",
            "live_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "run_id": {"help_text": "Run that generated this proposal."},
            "proposal_type": {"help_text": "New article or bounded page improvement."},
            "lifecycle_status": {"help_text": "Review, delivery, publication, and measurement lifecycle status."},
            "title": {"help_text": "Review title for this proposal."},
            "target_query": {"help_text": "Primary query or topic targeted by this proposal."},
            "target_url": {"help_text": "Existing or intended public URL."},
            "audience": {"help_text": "Intended reader."},
            "search_intent": {"help_text": "Reader need this proposal addresses."},
            "expected_outcome": {"help_text": "Opportunity statement without a guaranteed forecast."},
            "original_markdown": {"help_text": "Existing content for page-improvement diffs."},
            "proposed_markdown": {"help_text": "Full proposed Markdown after edits."},
            "delivery_state": {"help_text": "Current export or pull-request delivery state."},
            "delivery_reference": {"help_text": "Export filename or GitHub branch reference."},
            "pull_request_url": {"help_text": "Created GitHub pull request URL."},
            "live_url": {"help_text": "Verified public URL after publication."},
        }


class ContentAutopilotProposalListQuerySerializer(serializers.Serializer):
    run_id = serializers.UUIDField(required=False, help_text="Only return proposals from this content run.")
    profile_id = serializers.UUIDField(required=False, help_text="Only return proposals for this site profile.")


class ContentAutopilotMeasurementSerializer(serializers.ModelSerializer):
    baseline = ContentAutopilotMetricSerializer(help_text="Metrics captured before publication.")
    day_28 = ContentAutopilotMetricSerializer(help_text="Metrics captured 28 days after publication.")
    day_56 = ContentAutopilotMetricSerializer(help_text="Metrics captured 56 days after publication.")
    site_wide_controls = ContentAutopilotMetricSerializer(help_text="Site-wide metrics over the same windows.")

    class Meta:
        model = ContentAutopilotMeasurement
        fields = [
            "id",
            "proposal_id",
            "baseline",
            "day_28",
            "day_56",
            "site_wide_controls",
            "outcome_classification",
            "is_confounded",
            "baseline_at",
            "day_28_at",
            "day_56_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "proposal_id": {"help_text": "Proposal being measured."},
            "outcome_classification": {"help_text": "Improved, inconclusive, declined, or pending."},
            "is_confounded": {"help_text": "Whether another page change overlapped the measurement window."},
        }


class ContentAutopilotProposalEditRequestSerializer(serializers.Serializer):
    proposed_markdown = serializers.CharField(help_text="Edited Markdown to save for review.")
    content_package = ContentAutopilotPackageSerializer(help_text="Updated canonical delivery package.")


class ContentAutopilotExportResponseSerializer(serializers.Serializer):
    filename = serializers.CharField(help_text="Suggested export filename.")
    markdown = serializers.CharField(help_text="Validated Markdown content.")
    content_package = ContentAutopilotPackageSerializer(help_text="Structured JSON package for a CMS adapter.")


class ContentAutopilotPullRequestRequestSerializer(serializers.Serializer):
    proposal_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=5,
        help_text="One new article or up to five page improvements from the same run.",
    )


class ContentAutopilotPullRequestResponseSerializer(serializers.Serializer):
    pull_request_url = serializers.URLField(help_text="Created GitHub pull request URL.")
    branch = serializers.CharField(help_text="Created content branch.")


class ContentAutopilotSiteProfileViewSet(ContentAutopilotViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ContentAutopilotSiteProfileSerializer
    queryset = ContentAutopilotSiteProfile.objects.unscoped()
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def safely_get_queryset(
        self, queryset: QuerySet[ContentAutopilotSiteProfile]
    ) -> QuerySet[ContentAutopilotSiteProfile]:
        return ContentAutopilotSiteProfile.objects.for_team(self.team_id).order_by("created_at")

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
        result = discover_site(request.validated_data["domain"])
        return Response(ContentAutopilotSiteDiscoveryResponseSerializer(instance=result).data)


@extend_schema_view(list=extend_schema(parameters=[ContentAutopilotRunListQuerySerializer]))
class ContentAutopilotRunViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotRunSerializer
    queryset = ContentAutopilotRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[ContentAutopilotRun]) -> QuerySet[ContentAutopilotRun]:
        queryset = ContentAutopilotRun.objects.for_team(self.team_id)
        if self.action == "list":
            query_serializer = ContentAutopilotRunListQuerySerializer(data=self.request.query_params)
            query_serializer.is_valid(raise_exception=True)
            profile_id = query_serializer.validated_data.get("profile_id")
            if profile_id:
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
        try:
            run = start_run(
                team=self.team,
                profile_id=str(request.validated_data["profile_id"]),
                triggered_by_id=getattr(request.user, "id", None),
            )
        except ContentAutopilotLifecycleError as error:
            raise ValidationError(str(error)) from error
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
        try:
            run = cancel_run(run=self.get_object())
        except ContentAutopilotLifecycleError as error:
            raise ValidationError(str(error)) from error
        return Response(self.get_serializer(run).data)


@extend_schema_view(list=extend_schema(parameters=[ContentAutopilotProposalListQuerySerializer]))
class ContentAutopilotProposalViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotProposalSerializer
    queryset = ContentAutopilotProposal.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[ContentAutopilotProposal]) -> QuerySet[ContentAutopilotProposal]:
        queryset = ContentAutopilotProposal.objects.for_team(self.team_id).select_related("run")
        if self.action == "list":
            query_serializer = ContentAutopilotProposalListQuerySerializer(data=self.request.query_params)
            query_serializer.is_valid(raise_exception=True)
            run_id = query_serializer.validated_data.get("run_id")
            profile_id = query_serializer.validated_data.get("profile_id")
            if run_id:
                queryset = queryset.filter(run_id=run_id)
            if profile_id:
                queryset = queryset.filter(run__profile_id=profile_id)
        return queryset.order_by("proposal_type", "created_at")

    @validated_request(
        request_serializer=ContentAutopilotProposalEditRequestSerializer,
        operation_id="web_analytics_content_autopilot_proposals_edit",
        summary="Edit a content proposal",
        description="Saves reviewed Markdown and its canonical delivery package without publishing it.",
        responses={200: OpenApiResponse(response=ContentAutopilotProposalSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def edit(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        try:
            proposal = edit_proposal(proposal=self.get_object(), **request.validated_data)
        except ContentAutopilotLifecycleError as error:
            raise ValidationError(str(error)) from error
        return Response(self.get_serializer(proposal).data)

    @validated_request(
        operation_id="web_analytics_content_autopilot_proposals_reject",
        summary="Reject a content proposal",
        description="Rejects a proposal without changing the public site or repository.",
        responses={200: OpenApiResponse(response=ContentAutopilotProposalSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def reject(self, request: Request, **kwargs: Any) -> Response:
        try:
            proposal = reject_proposal(proposal=self.get_object())
        except ContentAutopilotLifecycleError as error:
            raise ValidationError(str(error)) from error
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
        try:
            proposal = regenerate_proposal(proposal=self.get_object())
        except ContentAutopilotLifecycleError as error:
            raise ValidationError(str(error)) from error
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
        try:
            filename, markdown, content_package = export_proposal(proposal=self.get_object())
        except (ContentAutopilotDeliveryError, ContentAutopilotLifecycleError) as error:
            raise ValidationError(str(error)) from error
        return Response({"filename": filename, "markdown": markdown, "content_package": content_package})

    @validated_request(
        request_serializer=ContentAutopilotPullRequestRequestSerializer,
        operation_id="web_analytics_content_autopilot_proposals_open_pull_request",
        summary="Open a content pull request",
        description="Commits approved files to a content-only branch and opens a pull request. It never merges.",
        responses={201: OpenApiResponse(response=ContentAutopilotPullRequestResponseSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"], required_scopes=["web_analytics:write"])
    def open_pull_request(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        try:
            pull_request_url, branch = open_pull_request(
                team_id=self.team_id,
                proposal_ids=[str(proposal_id) for proposal_id in request.validated_data["proposal_ids"]],
            )
        except (ContentAutopilotDeliveryError, ContentAutopilotLifecycleError) as error:
            raise ValidationError(str(error)) from error
        return Response(
            {"pull_request_url": pull_request_url, "branch": branch},
            status=status.HTTP_201_CREATED,
        )


class ContentAutopilotMeasurementViewSet(ContentAutopilotViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ContentAutopilotMeasurementSerializer
    queryset = ContentAutopilotMeasurement.objects.unscoped()

    def safely_get_queryset(
        self, queryset: QuerySet[ContentAutopilotMeasurement]
    ) -> QuerySet[ContentAutopilotMeasurement]:
        return ContentAutopilotMeasurement.objects.for_team(self.team_id).order_by("-created_at")
