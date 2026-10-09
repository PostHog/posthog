import logging
from typing import Any, cast

from django.db import transaction

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.api.repositories import (
    UUID_PATH_PATTERN,
    AutomaticReviewDecisionSerializer,
    EffectiveTeamStrictManagementPermission,
    ReviewHogProjectViewSetMixin,
    ReviewHogSettingsErrorSerializer,
    ReviewInstallationSerializer,
    ReviewProjectRefSerializer,
    ReviewRepositoryPersonRequestSerializer,
    ReviewRepositoryPersonSerializer,
    check_active_member,
    decision_data,
    installation_data,
    project_ref_data,
)
from products.review_hog.backend.automatic_review_rules import load_people
from products.review_hog.backend.models import (
    AutomaticFlashFor,
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
)
from products.review_hog.backend.preferences import InvalidPreference, UrgencyThreshold
from products.review_hog.backend.repository_settings import (
    OverviewEntry,
    RepositoryOverview,
    RepositoryOverviewView,
    RepositoryOwnerKind,
)

logger = logging.getLogger(__name__)


class ReviewProjectSettingsSerializer(serializers.Serializer):
    flash_for = serializers.ChoiceField(
        choices=AutomaticFlashFor.choices,
        required=False,
        help_text="Who gets automatic Flash reviews in the repositories this project reviews: 'everyone' (except "
        "the excepted people), 'listed' (only the listed people), or 'off' (only people who opt in, the "
        "default). A repository exception or a person's own choice wins over it.",
    )
    bot_prs = serializers.ChoiceField(
        choices=ReviewProjectSettings.BotPullRequests.choices,
        required=False,
        help_text="Pull requests from bots, and from authors who are not project members, in every repository "
        "this project reviews: 'skip' (not reviewed, the default) or 'run' (automatic Flash that runs as the "
        "person who connected GitHub, with default settings and no changes to the pull request).",
    )
    urgency_threshold = serializers.ChoiceField(
        choices=UrgencyThreshold.choices,
        required=False,
        help_text="Project default for the minimum priority a Full review publishes: 'consider' (all, the "
        "built-in default), 'should_fix', or 'must_fix'. A person's own value wins.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        required=False,
        help_text="Project default for the image in a Full review that finds nothing to raise. On by default. "
        "A person's own value wins.",
    )
    people = ReviewRepositoryPersonSerializer(
        many=True,
        read_only=True,
        help_text="The people on the project rule's two lists. Only the list that matches flash_for has an effect.",
    )
    installations = ReviewInstallationSerializer(
        many=True,
        read_only=True,
        help_text="Every GitHub installation connected to this project, and which of its repositories this "
        "project reviews.",
    )
    can_edit = serializers.BooleanField(
        read_only=True, help_text="Whether the requesting user is a project admin and can change these settings."
    )


class ReviewRepositoryOverviewQuerySerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=64, help_text="The GitHub App installation to list.")
    search = serializers.CharField(
        required=False, default="", allow_blank=True, help_text="Only repositories whose name contains this text."
    )
    view = serializers.ChoiceField(
        choices=RepositoryOverviewView.choices,
        required=False,
        default="all",
        help_text="'all' repositories, 'in_project' (reviewed by this project), 'exceptions' (with a repository "
        "exception), or 'mine' (with the requesting user's own choice).",
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Entries to skip.")
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200, help_text="Entries per page (max 200)."
    )


class ReviewRepositoryExceptionSerializer(serializers.Serializer):
    flash_for = serializers.ChoiceField(
        choices=AutomaticFlashFor.choices, help_text="The exception's rule: 'everyone', 'listed', or 'off'."
    )
    people = ReviewRepositoryPersonSerializer(many=True, help_text="The people on the exception's two lists.")


class ReviewRepositoryOverviewEntrySerializer(serializers.Serializer):
    full_name = serializers.CharField(help_text="GitHub repository in 'owner/name' form.")
    github_repo_id = serializers.IntegerField(allow_null=True, help_text="GitHub's repository id.")
    owner = serializers.ChoiceField(
        choices=RepositoryOwnerKind.choices,
        help_text="Which project reviews the repository: 'this_project', 'other_project', or 'none'.",
    )
    owner_project = ReviewProjectRefSerializer(
        allow_null=True, help_text="The other project that reviews the repository, when owner is 'other_project'."
    )
    in_project = serializers.BooleanField(help_text="Whether this project reviews the repository.")
    selected = serializers.BooleanField(help_text="Whether this project selected the repository explicitly.")
    repository_id = serializers.UUIDField(
        allow_null=True, help_text="Id of this project's repository entry, for the people list endpoints."
    )
    exception = ReviewRepositoryExceptionSerializer(
        allow_null=True, help_text="This project's repository exception. Null when the repository follows the project."
    )
    my_choice = serializers.ChoiceField(
        choices=ReviewUserRepositoryChoice.Mode.choices,
        allow_null=True,
        help_text="The requesting user's own choice for this repository: 'flash', 'off', or null.",
    )
    my_choice_id = serializers.UUIDField(allow_null=True, help_text="Id of that choice, to clear it.")
    my_result = AutomaticReviewDecisionSerializer(
        help_text="What the requesting user's own pull requests get here, and the rule that decided it."
    )
    inherited_result = AutomaticReviewDecisionSerializer(
        help_text="What the requesting user's own pull requests would get here without their choice for this "
        "repository. Equals my_result when there is no choice."
    )


class ReviewRepositoryOverviewSerializer(serializers.Serializer):
    installation_id = serializers.CharField(help_text="The listed GitHub App installation.")
    claim_scope = serializers.ChoiceField(
        choices=ReviewInstallationClaim.Scope.choices,
        allow_null=True,
        help_text="This project's claim on the installation: 'all', 'selected', or null.",
    )
    results = ReviewRepositoryOverviewEntrySerializer(many=True, help_text="One page of repositories.")
    total = serializers.IntegerField(help_text="Repositories that match the search and the view.")
    has_more = serializers.BooleanField(help_text="Whether more entries follow this page.")
    next_offset = serializers.IntegerField(allow_null=True, help_text="Offset of the next page, or null.")


def _entry_data(entry: OverviewEntry) -> dict[str, Any]:
    repository = entry.repository
    exception = None
    if repository is not None and repository.flash_for is not None:
        exception = {
            "flash_for": repository.flash_for,
            "people": [dict(ReviewRepositoryPersonSerializer(person).data) for person in entry.exception_people],
        }
    return {
        "full_name": entry.full_name,
        "github_repo_id": entry.github_repo_id,
        "owner": entry.owner,
        "owner_project": project_ref_data(entry.owner_project),
        "in_project": entry.in_project,
        "selected": entry.selected,
        "repository_id": repository.id if repository is not None else None,
        "exception": exception,
        "my_choice": entry.my_choice.mode if entry.my_choice is not None else None,
        "my_choice_id": entry.my_choice.id if entry.my_choice is not None else None,
        "my_result": decision_data(entry.my_result),
        "inherited_result": decision_data(entry.inherited_result),
    }


class ReviewProjectSettingsViewSet(ReviewHogProjectViewSetMixin, viewsets.GenericViewSet):
    """The project-wide ReviewHog rule and the repository overview.

    Project members can read everything here. Only project admins can change the rule and its lists,
    and every change goes to the activity log.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamStrictManagementPermission]
    posthog_feature_flag = "review-hog"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewProjectSettings.objects.unscoped()
    serializer_class = ReviewProjectSettingsSerializer

    def _settings_response(self, response_status: int = status.HTTP_200_OK) -> Response:
        team_id = self.effective_team_id
        row = ReviewProjectSettings.load(team_id)
        defaults = row.defaults
        data = {
            "flash_for": row.flash_for,
            "bot_prs": row.bot_prs,
            "urgency_threshold": defaults.urgency_threshold,
            "celebrate_clean_reviews": defaults.celebrate_clean_reviews,
            "people": load_people(team_id, [])[None],
            "installations": [installation_data(summary) for summary in self.project_repositories().installations()],
            "can_edit": self.is_effective_team_admin(),
        }
        return Response(ReviewProjectSettingsSerializer(data).data, status=response_status)

    def _settings_row(self) -> ReviewProjectSettings:
        team_id = self.effective_team_id
        row, _created = ReviewProjectSettings.objects.for_team(team_id, canonical=True).get_or_create(team_id=team_id)
        return row

    @extend_schema(
        methods=["GET"],
        responses={200: OpenApiResponse(response=ReviewProjectSettingsSerializer)},
        summary="Get the project's ReviewHog rule",
        description="The project rule for automatic Flash reviews, bot pull requests, the Full review defaults, "
        "and the connected GitHub installations.",
    )
    @extend_schema(
        methods=["PATCH"],
        request=ReviewProjectSettingsSerializer,
        responses={
            200: OpenApiResponse(response=ReviewProjectSettingsSerializer, description="The updated rule."),
            400: OpenApiResponse(description="Invalid field value."),
            403: OpenApiResponse(description="Only project admins can change the rule."),
        },
        summary="Update the project's ReviewHog rule",
        description="Partially update the project rule. Only the provided fields change. Project admins only.",
    )
    @action(detail=False, methods=["GET", "PATCH"], url_path="project_settings", url_name="project_settings")
    def project_settings(self, request: Request, **kwargs: Any) -> Response:
        if request.method == "PATCH":
            serializer = ReviewProjectSettingsSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            with transaction.atomic():
                row = (
                    ReviewProjectSettings.objects.for_team(self.effective_team_id)
                    .select_for_update()
                    .get(id=self._settings_row().id)
                )
                for field in ("flash_for", "bot_prs"):
                    if field in data:
                        setattr(row, field, data[field])
                changes = {key: data[key] for key in ("urgency_threshold", "celebrate_clean_reviews") if key in data}
                try:
                    row.preferences = row.defaults.with_changes(changes)
                except InvalidPreference as error:
                    raise serializers.ValidationError({error.key: str(error)})
                row.save()
        return self._settings_response()

    @extend_schema(
        request=ReviewRepositoryPersonRequestSerializer,
        responses={
            200: OpenApiResponse(response=ReviewProjectSettingsSerializer, description="Already on that list."),
            201: OpenApiResponse(response=ReviewProjectSettingsSerializer, description="The person was added."),
            400: OpenApiResponse(description="The user is not an active member of this project's organization."),
        },
        summary="Add a person to a project rule list",
        description="Add a project member to the project rule's 'listed' or 'excepted' list. Project admins only.",
    )
    @action(detail=False, methods=["POST"], url_path="project_settings/people", required_scopes=["review_hog:write"])
    def add_project_person(self, request: Request, **kwargs: Any) -> Response:
        serializer = ReviewRepositoryPersonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id: int = serializer.validated_data["user_id"]
        check_active_member(self.team, user_id)
        # The row exists first, so the activity log has an item to attach the list change to.
        self._settings_row()
        created = self.project_repositories().add_person(None, user_id=user_id, kind=serializer.validated_data["kind"])
        return self._settings_response(status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(
        parameters=[OpenApiParameter("person_id", str, OpenApiParameter.PATH, description="Id of the list entry.")],
        responses={
            200: OpenApiResponse(response=ReviewProjectSettingsSerializer, description="The person was removed."),
            404: OpenApiResponse(response=ReviewHogSettingsErrorSerializer, description="No such list entry."),
        },
        summary="Remove a person from a project rule list",
        description="Remove one entry from the project rule's 'listed' or 'excepted' list. Project admins only.",
    )
    @action(
        detail=False,
        methods=["DELETE"],
        url_path=rf"project_settings/people/(?P<person_id>{UUID_PATH_PATTERN})",
        required_scopes=["review_hog:write"],
    )
    def remove_project_person(self, request: Request, person_id: str, **kwargs: Any) -> Response:
        person = (
            ReviewRepositoryPerson.objects.for_team(self.effective_team_id, canonical=True)
            .filter(repository__isnull=True, id=person_id)
            .first()
        )
        if person is None:
            return Response(
                {"error": "No such list entry.", "conflicting_project": None}, status=status.HTTP_404_NOT_FOUND
            )
        person.delete()
        return self._settings_response()

    @extend_schema(
        parameters=[ReviewRepositoryOverviewQuerySerializer],
        responses={
            200: OpenApiResponse(response=ReviewRepositoryOverviewSerializer),
            400: OpenApiResponse(
                response=ReviewHogSettingsErrorSerializer, description="The installation is not connected here."
            ),
        },
        summary="List the repositories of a GitHub installation with their review settings",
        description="Every repository the GitHub installation can see, with the project that reviews it, this "
        "project's settings, the requesting user's choice, and the automatic review the requesting user gets.",
    )
    @action(detail=False, methods=["GET"], url_path="repository_overview", url_name="repository_overview")
    def repository_overview(self, request: Request, **kwargs: Any) -> Response:
        query = ReviewRepositoryOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        installation_id: str = query.validated_data["installation_id"]
        integration = Integration.objects.filter(
            team_id=self.effective_team_id, kind="github", integration_id=installation_id
        ).first()
        if integration is None:
            return Response(
                {"error": "This project has no GitHub connection for that installation.", "conflicting_project": None},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            repositories = GitHubIntegration(integration).list_all_cached_repositories()
        except Exception:
            # The list refreshes from GitHub when the cache is cold, and GitHub can fail or rate limit.
            logger.warning("review_hog_repository_overview_list_failed", exc_info=True)
            return Response(
                {"error": "GitHub did not return the repository list. Try again shortly.", "conflicting_project": None},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        search = query.validated_data["search"].strip().casefold()
        if search:
            repositories = [
                repository for repository in repositories if search in str(repository["full_name"]).casefold()
            ]
        overview = RepositoryOverview(self.effective_team, cast(User, request.user), installation_id, repositories)
        offset: int = query.validated_data["offset"]
        entries, total = overview.page(
            repositories, view=query.validated_data["view"], offset=offset, limit=query.validated_data["limit"]
        )
        has_more = offset + len(entries) < total
        claim = (
            ReviewInstallationClaim.objects.for_team(self.effective_team_id)
            .filter(installation_id=installation_id)
            .first()
        )
        data = {
            "installation_id": installation_id,
            "claim_scope": claim.scope if claim is not None else None,
            "results": [_entry_data(entry) for entry in entries],
            "total": total,
            "has_more": has_more,
            "next_offset": offset + len(entries) if has_more else None,
        }
        return Response(ReviewRepositoryOverviewSerializer(data).data)
