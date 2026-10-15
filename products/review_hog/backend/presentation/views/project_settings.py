from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.facade.api import (
    add_review_repository_person,
    get_review_project_settings,
    get_review_repository_overview,
    remove_review_repository_person,
    update_review_project_settings,
)
from products.review_hog.backend.facade.contracts import (
    GitHubRepositoryListError,
    InvalidPreference,
    PersonNotActiveMemberError,
    RepositorySettingsError,
    ReviewRepositoryOverviewEntry,
)
from products.review_hog.backend.facade.enums import (
    AutomaticFlashFor,
    RepositoryOverviewView,
    RepositoryOwnerKind,
    ReviewInstallationClaimScope,
    ReviewProjectSettingsBotPullRequests,
    ReviewRepositoryPersonKind,
    ReviewUserRepositoryChoiceMode,
    UrgencyThreshold,
)
from products.review_hog.backend.presentation.views.repositories import (
    UUID_PATH_PATTERN,
    AutomaticReviewDecisionSerializer,
    EffectiveTeamStrictManagementPermission,
    ReviewHogProjectViewSetMixin,
    ReviewHogSettingsErrorSerializer,
    ReviewInstallationSerializer,
    ReviewProjectRefSerializer,
    ReviewRepositoryPersonRequestSerializer,
    ReviewRepositoryPersonSerializer,
    bad_request_response,
    decision_data,
    installation_data,
    no_such_list_entry_response,
    not_active_member_error,
    project_ref_data,
)


class ReviewProjectSettingsSerializer(serializers.Serializer):
    flash_for = serializers.ChoiceField(
        choices=AutomaticFlashFor.choices,
        required=False,
        help_text="Who gets automatic Standard reviews in the repositories this project reviews: 'everyone' (except "
        "the excepted people), 'listed' (only the listed people), or 'off' (only people who opt in, the "
        "default). A repository exception or a person's own choice wins over it.",
    )
    bot_prs = serializers.ChoiceField(
        choices=ReviewProjectSettingsBotPullRequests.choices,
        required=False,
        help_text="Pull requests from bots, and from authors who are not project members, in every repository "
        "this project reviews: 'skip' (not reviewed, the default) or 'run' (an automatic Standard review that runs as the "
        "person who connected GitHub, with default settings and no changes to the pull request).",
    )
    urgency_threshold = serializers.ChoiceField(
        choices=UrgencyThreshold.choices,
        required=False,
        help_text="Project default for the minimum priority a Deep review publishes: 'consider' (all, the "
        "built-in default), 'should_fix', or 'must_fix'. A person's own value wins.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        required=False,
        help_text="Project default for the image in a Deep review that finds nothing to raise. On by default. "
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
        "exception), 'mine' (with the requesting user's own choice), or 'differs' (every repository except the ones "
        "this project reviews with no exception and no own choice, which the response counts as 'folded').",
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
        choices=ReviewUserRepositoryChoiceMode.choices,
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
    repository_result = AutomaticReviewDecisionSerializer(
        help_text="What the requesting user's own pull requests would get here from the repository exception or "
        "the project rule alone, without their default and their choice for this repository."
    )


class ReviewRepositoryOverviewSerializer(serializers.Serializer):
    installation_id = serializers.CharField(help_text="The listed GitHub App installation.")
    claim_scope = serializers.ChoiceField(
        choices=ReviewInstallationClaimScope.choices,
        allow_null=True,
        help_text="This project's claim on the installation: 'all', 'selected', or null.",
    )
    results = ReviewRepositoryOverviewEntrySerializer(many=True, help_text="One page of repositories.")
    total = serializers.IntegerField(help_text="Repositories that match the search and the view.")
    has_more = serializers.BooleanField(help_text="Whether more entries follow this page.")
    next_offset = serializers.IntegerField(allow_null=True, help_text="Offset of the next page, or null.")
    folded = serializers.IntegerField(
        help_text="With view 'differs', or 'all' without a search: how many repositories 'differs' leaves out "
        "because this project reviews them with no exception and no own choice. 0 otherwise."
    )
    folded_preview = serializers.ListField(
        child=serializers.CharField(),
        help_text="With view 'differs', or 'all' without a search: the names of the first left-out repositories, "
        "at most 3. Empty otherwise.",
    )
    folded_result = AutomaticReviewDecisionSerializer(
        allow_null=True,
        help_text="With view 'differs', or 'all' without a search: what the requesting user's own pull requests get "
        "in every left-out repository, which is the same for all of them. Null otherwise, or when nothing is left out.",
    )
    my_choices_unlike_default = serializers.IntegerField(
        help_text="How many of the requesting user's own repository choices in this project give something other "
        "than their default. Counts every installation, so the search, the view, and the page do not change it."
    )


def _entry_data(entry: ReviewRepositoryOverviewEntry) -> dict[str, Any]:
    exception = None
    if entry.exception is not None:
        exception = {
            "flash_for": entry.exception.flash_for,
            # Model rows: the response serializer renders them, and a pre-rendered row would reach the
            # nested user serializer as a dict.
            "people": list(entry.exception.people),
        }
    return {
        "full_name": entry.full_name,
        "github_repo_id": entry.github_repo_id,
        "owner": entry.owner,
        "owner_project": project_ref_data(entry.owner_project),
        "in_project": entry.in_project,
        "selected": entry.selected,
        "repository_id": entry.repository_id,
        "exception": exception,
        "my_choice": entry.my_choice,
        "my_choice_id": entry.my_choice_id,
        "my_result": decision_data(entry.my_result),
        "inherited_result": decision_data(entry.inherited_result),
        "repository_result": decision_data(entry.repository_result),
    }


class ReviewProjectSettingsViewSet(ReviewHogProjectViewSetMixin, viewsets.GenericViewSet):
    """The project-wide PostHog Review rule and the repository overview.

    Project members can read everything here. Only project admins can change the rule and its lists,
    and every change goes to the activity log.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamStrictManagementPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewProjectSettingsSerializer

    def _settings_response(self, response_status: int = status.HTTP_200_OK) -> Response:
        settings = get_review_project_settings(self.effective_team_id, self.acting_user_id)
        data = {
            "flash_for": settings.flash_for,
            "bot_prs": settings.bot_prs,
            "urgency_threshold": settings.urgency_threshold,
            "celebrate_clean_reviews": settings.celebrate_clean_reviews,
            "people": settings.people,
            "installations": [installation_data(installation) for installation in settings.installations],
            "can_edit": self.is_effective_team_admin(),
        }
        return Response(ReviewProjectSettingsSerializer(data).data, status=response_status)

    @extend_schema(
        methods=["GET"],
        responses={200: OpenApiResponse(response=ReviewProjectSettingsSerializer)},
        summary="Get the project's code review rule",
        description="The project rule for automatic Standard reviews, bot pull requests, the Deep review defaults, "
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
        summary="Update the project's code review rule",
        description="Partially update the project rule. Only the provided fields change. Project admins only.",
    )
    @action(detail=False, methods=["GET", "PATCH"], url_path="project_settings", url_name="project_settings")
    def project_settings(self, request: Request, **kwargs: Any) -> Response:
        if request.method == "PATCH":
            serializer = ReviewProjectSettingsSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                update_review_project_settings(self.effective_team_id, serializer.validated_data)
            except InvalidPreference as error:
                raise serializers.ValidationError({error.key: str(error)})
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
        try:
            created = add_review_repository_person(
                self.effective_team_id,
                self.acting_user_id,
                None,
                person_user_id=serializer.validated_data["user_id"],
                kind=ReviewRepositoryPersonKind(serializer.validated_data["kind"]),
            )
        except PersonNotActiveMemberError as error:
            raise not_active_member_error(error)
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
        if not remove_review_repository_person(self.effective_team_id, self.acting_user_id, None, UUID(person_id)):
            return no_such_list_entry_response()
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
        offset: int = query.validated_data["offset"]
        try:
            page = get_review_repository_overview(
                self.effective_team_id,
                self.acting_user_id,
                query.validated_data["installation_id"],
                search=query.validated_data["search"],
                view=RepositoryOverviewView(query.validated_data["view"]),
                offset=offset,
                limit=query.validated_data["limit"],
            )
        except RepositorySettingsError as error:
            return bad_request_response(error)
        except GitHubRepositoryListError as error:
            return Response({"error": str(error), "conflicting_project": None}, status=status.HTTP_502_BAD_GATEWAY)
        has_more = offset + len(page.entries) < page.total
        data = {
            "installation_id": page.installation_id,
            "claim_scope": page.claim_scope,
            "results": [_entry_data(entry) for entry in page.entries],
            "total": page.total,
            "has_more": has_more,
            "next_offset": offset + len(page.entries) if has_more else None,
            "folded": page.folded,
            "folded_preview": page.folded_preview,
            "folded_result": decision_data(page.folded_result) if page.folded_result is not None else None,
            "my_choices_unlike_default": page.my_choices_unlike_default,
        }
        return Response(ReviewRepositoryOverviewSerializer(data).data)
