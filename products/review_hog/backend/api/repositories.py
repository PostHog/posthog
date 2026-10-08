import re
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.automatic_review_rules import (
    AuthorPreferences,
    AutomaticReviewDecision,
    AutomaticReviewMode,
    AutomaticReviewReason,
    RepositoryReviewRule,
    load_author_preferences,
    load_repository_people,
)
from products.review_hog.backend.models import ReviewRepository, ReviewRepositoryPerson, ReviewUserRepositoryChoice

# GitHub owners and repository names use letters, digits, '-', '_' and '.'.
_FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@frozen
class _ViewerContext:
    """What a repository response needs beyond the row: its people and the viewer's own choices."""

    people: dict[UUID, list[ReviewRepositoryPerson]]
    viewer: AuthorPreferences


class ReviewRepositoryPersonSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of this list entry. Use it to remove the person.")
    user = UserBasicSerializer(read_only=True, help_text="The project member on the list.")
    kind = serializers.ChoiceField(
        choices=ReviewRepositoryPerson.Kind.choices,
        read_only=True,
        help_text="Which list: 'listed' (gets Flash when the repository reviews only listed people) or "
        "'excepted' (skipped when the repository reviews everyone).",
    )

    class Meta:
        model = ReviewRepositoryPerson
        fields = ["id", "user", "kind"]


class AutomaticReviewDecisionSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=AutomaticReviewMode.choices,
        help_text="The automatic review the requesting user's pull requests get in this repository: "
        "'flash', 'full', or 'none'.",
    )
    reason = serializers.ChoiceField(
        choices=AutomaticReviewReason.choices,
        help_text="Which rule decided the mode: 'own_repository_choice' and 'own_default' are the user's "
        "own choices; 'everyone', 'excepted', 'listed', and 'not_listed' come from the repository's "
        "rule; 'bot_excluded' applies to bot authors.",
    )


class ReviewRepositorySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the repository entry.")
    full_name = serializers.CharField(
        max_length=200,
        help_text="GitHub repository in 'owner/name' form, spelled as GitHub returns it (e.g. 'PostHog/posthog'). "
        "Compared case-insensitively; a repository can be added once per project.",
    )
    flash_for = serializers.ChoiceField(
        choices=ReviewRepository.FlashFor.choices,
        required=False,
        help_text="Who gets automatic Flash reviews when they follow the repository rules: 'everyone' (except the "
        "excepted people, the default) or 'listed' (only the listed people). A person's own choice always wins.",
    )
    exclude_bots = serializers.BooleanField(
        required=False,
        help_text="Skip automatic reviews of pull requests that bots open. On by default.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="Who added the repository.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the repository was added.")
    people = serializers.SerializerMethodField(
        help_text="The people on the repository's two lists. Only the list that matches flash_for has an effect."
    )
    my_choice = serializers.SerializerMethodField(
        help_text="The requesting user's own choice for their pull requests in this repository: 'flash', 'full', "
        "'off', or null when their default_review_mode applies."
    )
    my_result = serializers.SerializerMethodField(
        help_text="What the requesting user's own pull requests get in this repository, and the rule that decided it."
    )

    class Meta:
        model = ReviewRepository
        fields = [
            "id",
            "full_name",
            "flash_for",
            "exclude_bots",
            "created_by",
            "created_at",
            "people",
            "my_choice",
            "my_result",
        ]

    def _viewer_context(self) -> _ViewerContext:
        return cast(_ViewerContext, self.context["viewer_context"])

    def _people(self, instance: ReviewRepository) -> list[ReviewRepositoryPerson]:
        return self._viewer_context().people.get(instance.id, [])

    def validate_full_name(self, value: str) -> str:
        value = value.strip()
        if not _FULL_NAME_PATTERN.match(value):
            raise ValidationError("Use the 'owner/name' form, for example 'PostHog/posthog'.")
        return value

    @extend_schema_field(ReviewRepositoryPersonSerializer(many=True))
    def get_people(self, instance: ReviewRepository) -> list[ReturnDict]:
        return [ReviewRepositoryPersonSerializer(person).data for person in self._people(instance)]

    @extend_schema_field(serializers.ChoiceField(choices=ReviewUserRepositoryChoice.Mode.choices, allow_null=True))
    def get_my_choice(self, instance: ReviewRepository) -> str | None:
        choice = self._viewer_context().viewer.repository_choices.get(instance.id)
        return choice.value if choice is not None else None

    @extend_schema_field(AutomaticReviewDecisionSerializer)
    def get_my_result(self, instance: ReviewRepository) -> dict:
        context = self._viewer_context()
        rule = RepositoryReviewRule.for_repository(instance, self._people(instance))
        decision: AutomaticReviewDecision = rule.resolve(context.viewer.for_repository(instance.id))
        return {"mode": decision.mode.value, "reason": decision.reason.value}


class ReviewRepositoryUpdateSerializer(serializers.ModelSerializer):
    flash_for = serializers.ChoiceField(
        choices=ReviewRepository.FlashFor.choices,
        required=False,
        help_text="Who gets automatic Flash reviews when they follow the repository rules: 'everyone' (except the "
        "excepted people) or 'listed' (only the listed people).",
    )
    exclude_bots = serializers.BooleanField(
        required=False, help_text="Skip automatic reviews of pull requests that bots open."
    )

    class Meta:
        model = ReviewRepository
        fields = ["flash_for", "exclude_bots"]


class ReviewRepositoryPersonRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Id of the project member to add. Must be an active member.")
    kind = serializers.ChoiceField(
        choices=ReviewRepositoryPerson.Kind.choices,
        help_text="Which list to add the person to: 'listed' or 'excepted'.",
    )


class ReviewRepositoryChoiceRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=ReviewUserRepositoryChoice.Mode.choices,
        help_text="The requesting user's own automatic review for their pull requests in this repository: "
        "'flash', 'full', or 'off'. Clear the choice with DELETE to follow default_review_mode again.",
    )


class ReviewRepositoryErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Why the request was rejected.")


# `list` keeps the inherited method, because overriding it marks the viewset as a custom list for
# the pagination contract check. Its schema comes from the serializer and the class docstring.
@extend_schema_view(
    destroy=extend_schema(
        summary="Remove a repository",
        description="Remove the repository. Pull requests there stop getting automatic reviews, and its lists and "
        "everyone's own choices for it are deleted.",
    ),
)
class ReviewRepositoryViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The repositories where PostHog Review runs automatic reviews for this project.

    Any project member can add a repository, change its rule, and change its lists. Every such change
    goes to the activity log. The `my_choice` action stores the requesting user's own choice for their
    pull requests in one repository.
    """

    scope_object = "review_hog"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
    # Unscoped only to satisfy the router/introspection; `safely_get_queryset` scopes every read.
    queryset = ReviewRepository.objects.unscoped()
    serializer_class = ReviewRepositorySerializer
    pagination_class = None

    @property
    def effective_team_id(self) -> int:
        return resolve_effective_team_id(self.team_id)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            ReviewRepository.objects.for_team(self.effective_team_id, canonical=True)
            .select_related("created_by")
            .order_by("created_at")
        )

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        team_id = self.effective_team_id
        repository_ids = ReviewRepository.objects.for_team(team_id, canonical=True).values_list("id", flat=True)
        context["viewer_context"] = _ViewerContext(
            people=load_repository_people(team_id, repository_ids),
            viewer=load_author_preferences(team_id, user_id=self.request.user.id, is_bot=False),
        )
        return context

    def _repository_response(self, repository: ReviewRepository, response_status: int = status.HTTP_200_OK) -> Response:
        return Response(self.get_serializer(repository).data, status=response_status)

    @extend_schema(
        request=ReviewRepositorySerializer,
        responses={
            201: OpenApiResponse(response=ReviewRepositorySerializer, description="The added repository."),
            400: OpenApiResponse(description="Invalid name, or the repository is already added."),
        },
        summary="Add a repository",
        description="Add a GitHub repository, so pull requests there can get automatic reviews. By default everyone "
        "gets Flash reviews there, except bots and excepted people. A person's own choice always wins.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team_id = self.effective_team_id
        full_name = serializer.validated_data["full_name"]
        if ReviewRepository.objects.for_team(team_id, canonical=True).filter(full_name__iexact=full_name).exists():
            raise ValidationError({"full_name": f"{full_name} is already added."})
        try:
            # The savepoint keeps a concurrent add of the same repository from breaking the
            # surrounding transaction when the unique constraint fires.
            with transaction.atomic():
                repository = serializer.save(team_id=team_id, created_by=request.user)
        except IntegrityError:
            raise ValidationError({"full_name": f"{full_name} is already added."})
        return self._repository_response(repository, status.HTTP_201_CREATED)

    @extend_schema(
        request=ReviewRepositoryUpdateSerializer,
        responses={200: OpenApiResponse(response=ReviewRepositorySerializer, description="The updated repository.")},
        summary="Change a repository's rule",
        description="Change who gets automatic Flash reviews in the repository, and whether bots are excluded. "
        "Only the provided fields change.",
    )
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        repository = self.get_object()
        serializer = ReviewRepositoryUpdateSerializer(repository, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self._repository_response(repository)

    @extend_schema(
        request=ReviewRepositoryPersonRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ReviewRepositorySerializer, description="The person was already on that list."
            ),
            201: OpenApiResponse(response=ReviewRepositorySerializer, description="The person was added."),
            400: OpenApiResponse(description="The user is not an active member of this project's organization."),
        },
        summary="Add a person to a repository list",
        description="Add a project member to the repository's 'listed' or 'excepted' list.",
    )
    @action(detail=True, methods=["POST"], url_path="people", required_scopes=["review_hog:write"])
    def add_person(self, request: Request, **kwargs) -> Response:
        repository = self.get_object()
        serializer = ReviewRepositoryPersonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id: int = serializer.validated_data["user_id"]
        is_member = OrganizationMembership.objects.filter(
            organization_id=self.team.organization_id, user_id=user_id, user__is_active=True
        ).exists()
        if not is_member:
            raise ValidationError({"user_id": "This user is not an active member of the organization."})
        _person, created = ReviewRepositoryPerson.objects.for_team(repository.team_id, canonical=True).get_or_create(
            team_id=repository.team_id,
            repository=repository,
            user_id=user_id,
            kind=serializer.validated_data["kind"],
        )
        return self._repository_response(repository, status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(
        parameters=[OpenApiParameter("person_id", str, OpenApiParameter.PATH, description="Id of the list entry.")],
        responses={
            200: OpenApiResponse(response=ReviewRepositorySerializer, description="The person was removed."),
            404: OpenApiResponse(response=ReviewRepositoryErrorSerializer, description="No such list entry."),
        },
        summary="Remove a person from a repository list",
        description="Remove one entry from the repository's 'listed' or 'excepted' list.",
    )
    @action(
        detail=True,
        methods=["DELETE"],
        url_path=r"people/(?P<person_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        required_scopes=["review_hog:write"],
    )
    def remove_person(self, request: Request, person_id: str, **kwargs) -> Response:
        repository = self.get_object()
        person = (
            ReviewRepositoryPerson.objects.for_team(repository.team_id, canonical=True)
            .filter(repository=repository, id=person_id)
            .first()
        )
        if person is None:
            return Response({"error": "No such list entry."}, status=status.HTTP_404_NOT_FOUND)
        person.delete()
        return self._repository_response(repository)

    @extend_schema(
        methods=["PUT"],
        request=ReviewRepositoryChoiceRequestSerializer,
        responses={200: OpenApiResponse(response=ReviewRepositorySerializer, description="The choice was saved.")},
        summary="Set my choice for a repository",
        description="Set the requesting user's own automatic review for their pull requests in this repository. "
        "It wins over their default_review_mode and over the repository's rule.",
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        responses={200: OpenApiResponse(response=ReviewRepositorySerializer, description="The choice was cleared.")},
        summary="Clear my choice for a repository",
        description="Clear the requesting user's own choice for this repository, so their default_review_mode "
        "applies again.",
    )
    @action(detail=True, methods=["PUT", "DELETE"], url_path="my_choice", required_scopes=["review_hog:write"])
    def my_choice(self, request: Request, **kwargs) -> Response:
        repository = self.get_object()
        choices = ReviewUserRepositoryChoice.objects.for_team(repository.team_id, canonical=True)
        user = cast(User, request.user)
        if request.method == "DELETE":
            choices.filter(user_id=user.id, repository=repository).delete()
        else:
            serializer = ReviewRepositoryChoiceRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            choices.update_or_create(
                team_id=repository.team_id,
                user_id=user.id,
                repository=repository,
                defaults={"mode": serializer.validated_data["mode"]},
            )
        return self._repository_response(repository)
