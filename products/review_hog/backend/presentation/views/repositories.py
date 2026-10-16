import re
from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scoped_team_ids

from products.review_hog.backend.facade.api import (
    add_review_repository_person,
    create_review_installation_claim,
    delete_review_installation_claim,
    delete_review_repository,
    delete_review_repository_choice,
    get_review_installation_claim,
    get_review_repository,
    list_review_installation_claims,
    list_review_repositories,
    list_review_repository_choices,
    remove_review_repository_person,
    save_review_repository,
    save_review_repository_choice,
    update_review_installation_claim,
)
from products.review_hog.backend.facade.contracts import (
    UNSET,
    AutomaticReviewDecision,
    OwnershipConflict,
    PersonNotActiveMemberError,
    ProjectRef,
    RepositoryNotFoundError,
    RepositorySettingsError,
    ReviewInstallationInfo,
    ReviewRepositorySettings,
    Unset,
)
from products.review_hog.backend.facade.enums import (
    AutomaticFlashFor,
    AutomaticReviewReason,
    ReviewInstallationClaimScope,
    ReviewRepositoryPersonKind,
    ReviewUserRepositoryChoiceMode,
)

# GitHub owners and repository names use letters, digits, '-', '_' and '.'.
_FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
UUID_PATH_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def validate_full_name(value: str) -> str:
    value = value.strip()
    if not _FULL_NAME_PATTERN.match(value):
        raise ValidationError("Use the 'owner/name' form, for example 'PostHog/posthog'.")
    return value


def project_ref_data(project: ProjectRef | None) -> dict[str, Any] | None:
    if project is None:
        return None
    return {"id": project.team_id if project.name else None, "name": project.name}


def conflict_response(error: OwnershipConflict) -> Response:
    return Response(
        {"error": str(error), "conflicting_project": project_ref_data(error.project)},
        status=status.HTTP_409_CONFLICT,
    )


def bad_request_response(error: RepositorySettingsError) -> Response:
    return Response({"error": str(error), "conflicting_project": None}, status=status.HTTP_400_BAD_REQUEST)


def not_active_member_error(error: PersonNotActiveMemberError) -> ValidationError:
    return ValidationError({"user_id": str(error)})


def no_such_list_entry_response() -> Response:
    return Response({"error": "No such list entry.", "conflicting_project": None}, status=status.HTTP_404_NOT_FOUND)


def path_uuid(value: str) -> UUID:
    """The UUID of a detail URL. Any other value names no object, so the answer is 404."""
    try:
        return UUID(value)
    except ValueError:
        raise NotFound()


def uuid_path_parameter(object_name: str) -> OpenApiParameter:
    return OpenApiParameter(
        "id",
        OpenApiTypes.UUID,
        OpenApiParameter.PATH,
        description=f"A UUID string identifying this {object_name}.",
    )


def decision_data(decision: AutomaticReviewDecision) -> dict[str, Any]:
    return {"flash": decision.flash, "reason": decision.reason.value}


class ReviewProjectRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(
        allow_null=True, help_text="Id of the other project. Null when it belongs to another organization."
    )
    name = serializers.CharField(
        allow_null=True, help_text="Name of the other project. Null when it belongs to another organization."
    )


class ReviewHogSettingsErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Why the request was rejected.")
    conflicting_project = ReviewProjectRefSerializer(
        allow_null=True, help_text="The project that already holds the repository or the installation, if any."
    )


class ReviewRepositoryPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of this list entry. Use it to remove the person.")
    user = UserBasicSerializer(read_only=True, help_text="The project member on the list.")
    kind = serializers.ChoiceField(
        choices=ReviewRepositoryPersonKind.choices,
        read_only=True,
        help_text="Which list: 'listed' (gets automatic reviews when the rule reviews only listed people) or "
        "'excepted' (skipped when the rule reviews everyone).",
    )


class ReviewRepositoryPersonRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Id of the project member to add. Must be an active member.")
    kind = serializers.ChoiceField(
        choices=ReviewRepositoryPersonKind.choices,
        help_text="Which list to add the person to: 'listed' or 'excepted'.",
    )


class AutomaticReviewDecisionSerializer(serializers.Serializer):
    flash = serializers.BooleanField(
        help_text="Whether the requesting user's own pull requests get automatic Standard reviews in this repository."
    )
    reason = serializers.ChoiceField(
        choices=AutomaticReviewReason.choices,
        help_text="Which rule decided: the user's own choice ('own_repository_choice', 'own_default'), the "
        "repository exception ('repository_*'), the project rule ('project_*'), or 'not_in_project' when this "
        "project does not review the repository.",
    )


class ReviewRepositorySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the repository entry.")
    installation_id = serializers.CharField(read_only=True, help_text="The GitHub App installation that sees it.")
    github_repo_id = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="GitHub's id of the repository. Null until it is first seen."
    )
    full_name = serializers.CharField(read_only=True, help_text="GitHub repository in 'owner/name' form.")
    selected = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project selected the repository. A selected repository belongs to this project "
        "even when another project takes all repositories of the installation.",
    )
    flash_for = serializers.ChoiceField(
        choices=AutomaticFlashFor.choices,
        read_only=True,
        allow_null=True,
        help_text="The repository exception: 'everyone', 'listed', or 'off' (opt-in only). Null when the "
        "repository follows the project rule.",
    )
    people = serializers.SerializerMethodField(
        help_text="The people on the exception's two lists. Only the list that matches flash_for has an effect."
    )
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="Who added the repository.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the repository was added.")

    @extend_schema_field(ReviewRepositoryPersonSerializer(many=True))
    def get_people(self, instance: ReviewRepositorySettings) -> list[dict]:
        return [dict(ReviewRepositoryPersonSerializer(person).data) for person in instance.people]


class ReviewRepositoryWriteSerializer(serializers.Serializer):
    installation_id = serializers.CharField(
        max_length=64, help_text="The GitHub App installation that sees the repository, from the overview."
    )
    full_name = serializers.CharField(
        max_length=200, help_text="GitHub repository in 'owner/name' form, spelled as GitHub returns it."
    )
    github_repo_id = serializers.IntegerField(
        required=False, min_value=1, help_text="GitHub's id of the repository, from the overview. Keeps renames."
    )
    selected = serializers.BooleanField(
        required=False,
        help_text="True includes the repository into this project, also when another project takes all "
        "repositories of the installation. False removes it; with an 'only selected' claim its exception goes too.",
    )
    flash_for = serializers.ChoiceField(
        choices=AutomaticFlashFor.choices,
        required=False,
        allow_null=True,
        help_text="The repository exception: 'everyone', 'listed', or 'off'. Null clears it, so the repository "
        "follows the project rule again. Omit it to keep the current value.",
    )

    def validate_full_name(self, value: str) -> str:
        return validate_full_name(value)


class ReviewRepositoryWriteResponseSerializer(serializers.Serializer):
    repository = ReviewRepositorySerializer(
        allow_null=True,
        help_text="The repository entry after the write. Null when nothing is left to store, so the entry was "
        "deleted and the repository follows the project rule or left the project.",
    )
    taken_from_project = ReviewProjectRefSerializer(
        allow_null=True,
        help_text="The project that took all repositories of the installation, when this write took the "
        "repository from it.",
    )


class ReviewInstallationSerializer(serializers.Serializer):
    installation_id = serializers.CharField(help_text="The GitHub App installation id.")
    account_name = serializers.CharField(help_text="The GitHub account (organization or user) of the installation.")
    connected_by = UserBasicSerializer(
        allow_null=True,
        help_text="Who connected the installation to this project. Automatic Standard reviews of bot pull requests "
        "run as this user.",
    )
    claim_id = serializers.UUIDField(
        allow_null=True, help_text="Id of this project's claim. Null when the project reviews nothing there."
    )
    scope = serializers.ChoiceField(
        choices=ReviewInstallationClaimScope.choices,
        allow_null=True,
        help_text="Which repositories this project reviews: 'all' (every repository no other project selected, "
        "including future ones), 'selected' (only the selected ones), or null (none).",
    )
    all_taken_by_project = ReviewProjectRefSerializer(
        allow_null=True,
        help_text="Another project that takes all repositories of the installation, if any.",
    )


def installation_data(installation: ReviewInstallationInfo) -> dict[str, Any]:
    return {
        "installation_id": installation.installation_id,
        "account_name": installation.account_name,
        "connected_by": installation.connected_by,
        "claim_id": installation.claim_id,
        "scope": installation.scope,
        "all_taken_by_project": project_ref_data(installation.all_taken_by),
    }


class ReviewInstallationClaimSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the claim.")
    installation_id = serializers.CharField(read_only=True, help_text="The GitHub App installation id.")
    scope = serializers.ChoiceField(
        choices=ReviewInstallationClaimScope.choices,
        read_only=True,
        help_text="'all' (every repository no other project selected, including future ones) or 'selected'.",
    )
    account_name = serializers.SerializerMethodField(
        help_text="The GitHub account (organization or user) of the installation."
    )
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="Who made the claim.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the claim was made.")

    @extend_schema_field(serializers.CharField())
    def get_account_name(self, instance: Any) -> str:
        return instance.account_name


class ReviewInstallationClaimCreateSerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=64, help_text="The GitHub App installation id.")
    scope = serializers.ChoiceField(
        choices=ReviewInstallationClaimScope.choices,
        help_text="'all' reviews every repository of the installation that no other project selected. "
        "At most one project per installation can choose it. 'selected' reviews only selected repositories.",
    )


class ReviewInstallationClaimUpdateSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=ReviewInstallationClaimScope.choices,
        help_text="'all' or 'selected'. Switching to 'selected' removes the exceptions of the repositories that "
        "leave the project.",
    )


class ReviewRepositoryChoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the choice. Use it to clear the choice.")
    installation_id = serializers.CharField(read_only=True, help_text="The GitHub App installation.")
    github_repo_id = serializers.IntegerField(read_only=True, allow_null=True, help_text="GitHub's repository id.")
    full_name = serializers.CharField(read_only=True, help_text="GitHub repository in 'owner/name' form.")
    mode = serializers.ChoiceField(
        choices=ReviewUserRepositoryChoiceMode.choices,
        read_only=True,
        help_text="'flash' or 'off' for the user's own pull requests in this repository.",
    )


class ReviewRepositoryChoiceWriteSerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=64, help_text="The GitHub App installation.")
    full_name = serializers.CharField(max_length=200, help_text="GitHub repository in 'owner/name' form.")
    github_repo_id = serializers.IntegerField(required=False, min_value=1, help_text="GitHub's repository id.")
    mode = serializers.ChoiceField(
        choices=ReviewUserRepositoryChoiceMode.choices,
        help_text="The requesting user's own automatic review for their pull requests in this repository: "
        "'flash' or 'off'. A value equal to what the user inherits clears the choice instead.",
    )

    def validate_full_name(self, value: str) -> str:
        return validate_full_name(value)


class ReviewRepositoryChoiceWriteResponseSerializer(serializers.Serializer):
    choice = ReviewRepositoryChoiceSerializer(
        allow_null=True, help_text="The stored choice. Null when the value equals the inherited one."
    )
    my_result = AutomaticReviewDecisionSerializer(
        help_text="What the requesting user's own pull requests get in this repository after the write."
    )


class ReviewHogProjectViewSetMixin(TeamAndOrgViewSetMixin):
    """Shared plumbing for the project-wide settings viewsets: the root project and the acting user."""

    @property
    def effective_team_id(self) -> int:
        return resolve_effective_team_id(self.team_id)

    @property
    def effective_team(self) -> Team:
        team_id = self.effective_team_id
        return self.team if self.team.id == team_id else Team.objects.get(id=team_id)

    @property
    def acting_user_id(self) -> int:
        return cast(int, self.request.user.id)

    def is_effective_team_admin(self) -> bool:
        level = self.user_permissions.team(self.effective_team).effective_membership_level
        return level is not None and level >= OrganizationMembership.Level.ADMIN


class EffectiveTeamMemberPermission(BasePermission):
    """Members only, checked on the root project that holds the rows.

    An environment URL resolves to its parent project, and the default checks cover only the URL project.
    """

    message = "You don't have access to the project."

    def has_permission(self, request: Request, view: Any) -> bool:
        if not isinstance(view, ReviewHogProjectViewSetMixin):
            return False
        # The API scope check covers only the URL project, so a key scoped to an environment must not
        # reach its parent project.
        scoped_teams = get_authenticator_scoped_team_ids(request.successful_authenticator)
        if scoped_teams is not None and view.effective_team_id not in scoped_teams:
            return False
        return view.user_permissions.team(view.effective_team).effective_membership_level is not None


class EffectiveTeamStrictManagementPermission(EffectiveTeamMemberPermission):
    """Members read, admins write, both checked on the root project that the writes change.

    A user can be admin of the environment but only a member of the parent.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request: Request, view: Any) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.method in SAFE_METHODS or view.is_effective_team_admin()


@extend_schema_view(
    destroy=extend_schema(
        summary="Remove a repository's settings",
        description="Remove the repository from this project and clear its exception and lists. With an 'all "
        "repositories' claim the repository stays in the project and follows the project rule.",
        parameters=[uuid_path_parameter("review repository")],
    ),
)
class ReviewRepositoryViewSet(ReviewHogProjectViewSetMixin, viewsets.GenericViewSet):
    """The repositories this project has settings for: selected repositories and repository exceptions.

    Project members can read them. Only project admins can change them, and every change goes to the
    activity log. A repository has settings in one project at most.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamStrictManagementPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewRepositorySerializer
    pagination_class = None

    def _repository_or_404(self) -> ReviewRepositorySettings:
        repository_id = path_uuid(self.kwargs["pk"])
        repository = get_review_repository(self.effective_team_id, self.acting_user_id, repository_id)
        if repository is None:
            raise NotFound()
        return repository

    def _repository_response(self, repository_id: UUID, response_status: int = status.HTTP_200_OK) -> Response:
        repository = get_review_repository(self.effective_team_id, self.acting_user_id, repository_id)
        return Response(ReviewRepositorySerializer(repository).data, status=response_status)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        repositories = list_review_repositories(self.effective_team_id, self.acting_user_id)
        return Response(ReviewRepositorySerializer(repositories, many=True).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        repository_id = path_uuid(self.kwargs["pk"])
        if not delete_review_repository(self.effective_team_id, self.acting_user_id, repository_id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=ReviewRepositoryWriteSerializer,
        responses={
            200: OpenApiResponse(response=ReviewRepositoryWriteResponseSerializer, description="The saved settings."),
            400: OpenApiResponse(response=ReviewHogSettingsErrorSerializer, description="The rules forbid the write."),
            409: OpenApiResponse(
                response=ReviewHogSettingsErrorSerializer,
                description="Another project already has settings for the repository.",
            ),
        },
        summary="Save a repository's settings",
        description="Include a repository into this project, remove it, or set or clear its exception. Only the "
        "provided fields change. Including a repository that another project's 'all repositories' claim covers "
        "takes it from that project; the response names it.",
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReviewRepositoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        flash_for: AutomaticFlashFor | None | Unset = UNSET
        if "flash_for" in data:
            flash_for = AutomaticFlashFor(data["flash_for"]) if data["flash_for"] is not None else None
        try:
            result = save_review_repository(
                self.effective_team_id,
                self.acting_user_id,
                installation_id=data["installation_id"],
                full_name=data["full_name"],
                github_repo_id=data.get("github_repo_id"),
                selected=data.get("selected"),
                flash_for=flash_for,
            )
        except OwnershipConflict as error:
            return conflict_response(error)
        except RepositorySettingsError as error:
            return bad_request_response(error)
        response = ReviewRepositoryWriteResponseSerializer(
            {"repository": result.repository, "taken_from_project": project_ref_data(result.taken_from)}
        )
        return Response(response.data)

    @extend_schema(
        parameters=[uuid_path_parameter("review repository")],
        request=ReviewRepositoryPersonRequestSerializer,
        responses={
            200: OpenApiResponse(response=ReviewRepositorySerializer, description="The person was already on it."),
            201: OpenApiResponse(response=ReviewRepositorySerializer, description="The person was added."),
            400: OpenApiResponse(description="The user is not an active member of this project's organization."),
        },
        summary="Add a person to a repository exception list",
        description="Add a project member to the 'listed' or 'excepted' list of the repository exception.",
    )
    @action(detail=True, methods=["POST"], url_path="people", required_scopes=["review_hog:write"])
    def add_person(self, request: Request, **kwargs: Any) -> Response:
        repository = self._repository_or_404()
        serializer = ReviewRepositoryPersonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            created = add_review_repository_person(
                self.effective_team_id,
                self.acting_user_id,
                repository.id,
                person_user_id=serializer.validated_data["user_id"],
                kind=ReviewRepositoryPersonKind(serializer.validated_data["kind"]),
            )
        except PersonNotActiveMemberError as error:
            raise not_active_member_error(error)
        except RepositoryNotFoundError:
            raise NotFound()
        return self._repository_response(repository.id, status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            uuid_path_parameter("review repository"),
            OpenApiParameter("person_id", str, OpenApiParameter.PATH, description="Id of the list entry."),
        ],
        responses={
            200: OpenApiResponse(response=ReviewRepositorySerializer, description="The person was removed."),
            404: OpenApiResponse(response=ReviewHogSettingsErrorSerializer, description="No such list entry."),
        },
        summary="Remove a person from a repository exception list",
        description="Remove one entry from the 'listed' or 'excepted' list of the repository exception.",
    )
    @action(
        detail=True,
        methods=["DELETE"],
        url_path=rf"people/(?P<person_id>{UUID_PATH_PATTERN})",
        required_scopes=["review_hog:write"],
    )
    def remove_person(self, request: Request, person_id: str, **kwargs: Any) -> Response:
        repository = self._repository_or_404()
        if not remove_review_repository_person(
            self.effective_team_id, self.acting_user_id, repository.id, UUID(person_id)
        ):
            return no_such_list_entry_response()
        return self._repository_response(repository.id)


class ReviewInstallationClaimViewSet(ReviewHogProjectViewSetMixin, viewsets.GenericViewSet):
    """Which repositories of each connected GitHub installation this project reviews.

    Project members can read the claims. Only project admins can change them, and every change goes
    to the activity log. The project settings response lists every connected installation, also the
    ones without a claim.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamStrictManagementPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewInstallationClaimSerializer
    pagination_class = None

    def _claim_id_or_404(self) -> UUID:
        claim_id = path_uuid(self.kwargs["pk"])
        if get_review_installation_claim(self.effective_team_id, self.acting_user_id, claim_id) is None:
            raise NotFound()
        return claim_id

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        claims = list_review_installation_claims(self.effective_team_id, self.acting_user_id)
        return Response(ReviewInstallationClaimSerializer(claims, many=True).data)

    @extend_schema(
        request=ReviewInstallationClaimCreateSerializer,
        responses={
            201: OpenApiResponse(response=ReviewInstallationClaimSerializer, description="The claim was saved."),
            400: OpenApiResponse(response=ReviewHogSettingsErrorSerializer, description="The rules forbid it."),
            409: OpenApiResponse(
                response=ReviewHogSettingsErrorSerializer,
                description="Another project already takes all repositories of the installation.",
            ),
        },
        summary="Claim a GitHub installation",
        description="Choose which repositories of a connected GitHub installation this project reviews.",
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReviewInstallationClaimCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claim = create_review_installation_claim(
                self.effective_team_id,
                self.acting_user_id,
                serializer.validated_data["installation_id"],
                ReviewInstallationClaimScope(serializer.validated_data["scope"]),
            )
        except OwnershipConflict as error:
            return conflict_response(error)
        except RepositorySettingsError as error:
            return bad_request_response(error)
        return Response(ReviewInstallationClaimSerializer(claim).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[uuid_path_parameter("review installation claim")],
        request=ReviewInstallationClaimUpdateSerializer,
        responses={
            200: OpenApiResponse(response=ReviewInstallationClaimSerializer, description="The claim was changed."),
            409: OpenApiResponse(
                response=ReviewHogSettingsErrorSerializer,
                description="Another project already takes all repositories of the installation.",
            ),
        },
        summary="Change a GitHub installation claim",
        description="Switch between all repositories and only selected repositories. Switching to selected "
        "removes the exceptions of the repositories that leave this project. Personal choices stay.",
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        claim_id = self._claim_id_or_404()
        serializer = ReviewInstallationClaimUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claim = update_review_installation_claim(
                self.effective_team_id,
                self.acting_user_id,
                claim_id,
                ReviewInstallationClaimScope(serializer.validated_data["scope"]),
            )
        except OwnershipConflict as error:
            return conflict_response(error)
        if claim is None:
            raise NotFound()
        return Response(ReviewInstallationClaimSerializer(claim).data)

    @extend_schema(
        parameters=[uuid_path_parameter("review installation claim")],
        responses={
            204: OpenApiResponse(description="The claim and this project's repository settings there are gone.")
        },
        summary="Stop reviewing a GitHub installation",
        description="Remove the claim, so this project reviews no repository of the installation. Its selected "
        "repositories and exceptions there are removed too. Personal choices stay.",
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        claim_id = path_uuid(self.kwargs["pk"])
        if not delete_review_installation_claim(self.effective_team_id, self.acting_user_id, claim_id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    destroy=extend_schema(
        summary="Clear my choice for a repository",
        description="Clear the requesting user's own choice for one repository, so their default applies again.",
        parameters=[uuid_path_parameter("review user repository choice")],
    ),
)
class ReviewRepositoryChoiceViewSet(ReviewHogProjectViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's own automatic review choices for repositories of this project.

    Any project member can manage their own choices. A choice stores only what differs from what the
    user inherits, so picking the inherited value clears it.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission, EffectiveTeamMemberPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewRepositoryChoiceSerializer
    pagination_class = None

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        choices = list_review_repository_choices(self.effective_team_id, self.acting_user_id)
        return Response(ReviewRepositoryChoiceSerializer(choices, many=True).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        choice_id = path_uuid(self.kwargs["pk"])
        if not delete_review_repository_choice(self.effective_team_id, self.acting_user_id, choice_id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=ReviewRepositoryChoiceWriteSerializer,
        responses={
            200: OpenApiResponse(response=ReviewRepositoryChoiceWriteResponseSerializer, description="Saved."),
            400: OpenApiResponse(
                response=ReviewHogSettingsErrorSerializer, description="This project does not review the repository."
            ),
        },
        summary="Set my choice for a repository",
        description="Set the requesting user's own automatic review for their pull requests in one repository. "
        "It wins over their default and over the repository and project rules.",
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReviewRepositoryChoiceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = save_review_repository_choice(
                self.effective_team_id,
                self.acting_user_id,
                installation_id=data["installation_id"],
                full_name=data["full_name"],
                github_repo_id=data.get("github_repo_id"),
                mode=ReviewUserRepositoryChoiceMode(data["mode"]),
            )
        except RepositorySettingsError as error:
            return bad_request_response(error)
        response = ReviewRepositoryChoiceWriteResponseSerializer(
            {"choice": result.choice, "my_result": decision_data(result.my_result)}
        )
        return Response(response.data)
