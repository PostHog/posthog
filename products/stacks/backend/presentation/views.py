"""
DRF views for stacks.

Each view validates JSON, works out who is asking and for which exact project, checks that the caller holds the
scopes the run will use, calls the facade and serializes its contracts. No view returns a stack's record of what
it made, a saved diff or a secret value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings

import jwt
from drf_spectacular.utils import OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, WorkloadAccessTokenAuthentication
from posthog.exceptions import Conflict, InsufficientScope
from posthog.models.organization import OrganizationMembership
from posthog.models.workload_trust_policy import WorkloadTrustPolicy, workload_trust_policy_version
from posthog.permissions import get_authenticator_scopes, scopes_caller_lacks

from ..facade import api
from ..facade.contracts import (
    AdoptInput,
    AdoptResource,
    Binding,
    Caller,
    CallerGrant,
    ChangeRequestInput,
    DiffSource,
    ReconcileInput,
    RequestedChange,
    SetSecretInput,
    StackServiceError,
    StartDiffInput,
    StartPushInput,
)
from ..facade.enums import StackErrorKind
from .serializers import (
    AdoptableEntitySerializer,
    AdoptablePageSerializer,
    AdoptableQuerySerializer,
    AdoptRequestSerializer,
    AdoptResponseSerializer,
    BindingLookupQuerySerializer,
    BindingLookupSerializer,
    BindingSerializer,
    ContextPagesRequestSerializer,
    CreateDiffRequestSerializer,
    GeneratedModuleSerializer,
    GenerateModuleRequestSerializer,
    ManagedKindListSerializer,
    PushRequestSerializer,
    ReconciledSerializer,
    ReconcileRequestSerializer,
    SecretListSerializer,
    SecretSerializer,
    SecretWriteSerializer,
    StackChangeRequestSerializer,
    StackDiffSerializer,
    StackErrorResponseSerializer,
    StackSettingsSerializer,
    StartedChangeRequestSerializer,
)

_ERRORS = {
    code: OpenApiResponse(response=StackErrorResponseSerializer, description=description)
    for code, description in (
        (400, "The request is invalid. `code` says what to fix."),
        (401, "The request is not authenticated."),
        (403, "The caller lacks a scope the run needs (`required_scopes` lists them), or may not run it."),
        (404, "No such stack, diff, binding, secret or entity."),
        (409, "The stack changed or is locked, the diff cannot be pushed, or another stack manages the entity."),
        (503, "Stacks are not set up on this PostHog instance."),
    )
}


class Unavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "stacks_unavailable"


def _api_error(error: StackServiceError) -> exceptions.APIException:
    if error.kind == StackErrorKind.NOT_FOUND:
        return exceptions.NotFound(detail=error.message, code=error.code)
    if error.kind == StackErrorKind.CONFLICT:
        return Conflict(detail=error.message, code=error.code)
    if error.kind == StackErrorKind.FORBIDDEN:
        return exceptions.PermissionDenied(detail=error.message, code=error.code)
    if error.kind == StackErrorKind.UNAVAILABLE:
        return Unavailable(detail=error.message, code=error.code)
    return exceptions.ValidationError(detail=error.message, code=error.code)


def _require_scopes(request: Request, scopes: list[str]) -> None:
    """The engine runs with exactly these scopes, so a caller must hold them all."""
    missing = scopes_caller_lacks(request, scopes)
    if missing:
        raise InsufficientScope(
            missing,
            detail=f"This needs the {', '.join(missing)} scopes. Add them to your key, then try again.",
            extra={"required_scopes": missing},
        )


def _workload_expiry(request: Request) -> str:
    # The authenticator verified this token's signature and claims, so its `exp` is read without verifying again.
    token = request.META.get("HTTP_AUTHORIZATION", "").removeprefix("Bearer ").strip()
    try:
        expires = jwt.decode(token, options={"verify_signature": False}).get("exp")
    except jwt.PyJWTError:
        return ""
    return datetime.fromtimestamp(int(expires), tz=UTC).isoformat() if expires else ""


def _grant(request: Request) -> CallerGrant:
    """The credential, as a reference the worker can re-check. A credential it cannot re-check is refused here."""
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return CallerGrant(type="personal_api_key", id=str(authenticator.personal_api_key.id))
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        return CallerGrant(type="oauth", id=str(authenticator.access_token.id))
    if isinstance(authenticator, WorkloadAccessTokenAuthentication):
        policy = WorkloadTrustPolicy.objects.filter(pk=authenticator.policy_id).first()
        return CallerGrant(
            type="workload",
            id=str(authenticator.policy_id),
            version=workload_trust_policy_version(policy) if policy else "",
            expires_at=_workload_expiry(request),
        )
    if isinstance(authenticator, SessionAuthentication):
        return CallerGrant(type="session", id="")
    raise exceptions.PermissionDenied(
        detail="Stacks cannot run with this kind of credential. Sign in, or use a personal API key, an OAuth token "
        "or a workload token.",
        code="credential_not_supported",
    )


def _impersonated(request: Request) -> bool:
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, OAuthAccessTokenAuthentication) and authenticator.access_token.impersonated_by_id:
        return True
    return is_impersonated_session(request)


class StackViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Stacks: folders of definitions that PostHog keeps true in one project.

    A diff computes what a push would change. A push makes exactly one saved diff true.
    """

    scope_object = "stack"
    # A stack is not an access control resource, so team membership and API scopes decide access.
    records_have_object_access_rules = False
    lookup_field = "name"
    lookup_value_regex = "[a-z0-9][a-z0-9_-]*"
    path_parameters = {
        "name": PathParameter(type=str, description="The stack name, as `posthog.json` sets it."),
        "diff_id": PathParameter(type=UUID, description="The id of a saved diff of this stack."),
        "binding_id": PathParameter(type=UUID, description="The id of a binding of this stack."),
        "secret_name": PathParameter(
            type=str,
            description="The secret's name, as `secret('NAME')` uses it: letters, digits and underscores, starting "
            "with a letter or an underscore, at most 100 characters.",
        ),
    }
    pagination_class = FacadeLimitOffsetPagination
    serializer_class = StackDiffSerializer
    # These also need the scopes of the definition kinds the request names, which only the request says.
    request_dependent_scope_actions = frozenset({"diffs", "diff", "push", "adopt", "detach", "adoptable"})

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Before the first stacks query: an instance without the product refuses every route the same way. Module
        # generation reads and stores nothing, so it works without the product's database.
        if self.action != "modules":
            api.ensure_ready()

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, StackServiceError):
            exc = _api_error(exc)
        return super().handle_exception(exc)

    def _caller(self, request: Request) -> Caller:
        user_id = getattr(request.user, "id", None)
        if user_id is None:
            # The engine acts as the caller, so a credential with no user cannot run it.
            raise exceptions.PermissionDenied(
                detail="Use a personal API key or sign in to run stacks.", code="user_required"
            )
        level = self.user_permissions.team(self.team).effective_membership_level
        membership = self.user_access_control.organization_membership
        return Caller(
            user_id=user_id,
            grant=_grant(request),
            target_team_id=self.team.id,
            organization_id=str(self.team.organization_id),
            is_organization_admin=membership is not None and membership.level >= OrganizationMembership.Level.ADMIN,
            held_scopes=get_authenticator_scopes(getattr(request, "successful_authenticator", None)),
            is_project_admin=level is not None and level >= OrganizationMembership.Level.ADMIN,
            impersonated=_impersonated(request),
        )

    def _binding_payload(self, binding: Binding) -> dict[str, Any]:
        path = api.entity_path(kind=binding.kind, entity_id=binding.entity_id)
        return {
            "id": binding.id,
            "stack_name": binding.stack_name,
            "repository": binding.repository,
            "kind": binding.kind,
            "key": binding.key,
            "entity_id": binding.entity_id,
            "entity_url": f"{settings.SITE_URL.rstrip('/')}/project/{self.team.id}/{path}" if path else None,
            "source": {"file": binding.source_file, "export": binding.source_export} if binding.source_file else None,
            "status": binding.status,
            "owned_fields": list(binding.owned_fields),
        }

    @validated_request(
        request_serializer=CreateDiffRequestSerializer,
        responses={202: OpenApiResponse(response=StackDiffSerializer), **_ERRORS},
        summary="Start a diff",
        operation_id="stacks_diff_create",
        description="Save a diff of the description against the project and start computing it. Returns at once "
        "with status `running`. Creates the stack on its first diff. Needs the read scopes of every kind in the "
        "description and every kind the stack already manages.",
    )
    @action(detail=True, methods=["post"], url_path="diffs", required_scopes=["stack:read"])
    def diffs(self, request: ValidatedRequest, name: str, **kwargs: Any) -> Response:
        data = request.validated_data
        api.check_description_limits(data["description"])
        caller = self._caller(request)
        scopes = api.diff_scopes(team_id=self.team.id, stack_name=name, description=data["description"])
        _require_scopes(request, scopes)
        diff = api.start_diff(
            StartDiffInput(
                team_id=self.team.id,
                stack_name=name,
                description=data["description"],
                source=DiffSource(**data["source"]),
                caller=caller,
            ),
            scopes=scopes,
        )
        return Response(StackDiffSerializer(diff).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        responses={200: OpenApiResponse(response=StackDiffSerializer), **_ERRORS},
        summary="Read a diff",
        operation_id="stacks_diff_retrieve",
        description="The diff and its status. A push's progress shows here too. Needs the read scopes the diff ran "
        "with. Field values are shown to the person who made the diff and to project admins.",
    )
    @action(detail=True, methods=["get"], url_path=r"diffs/(?P<diff_id>[^/.]+)", required_scopes=["stack:read"])
    def diff(self, request: Request, name: str, diff_id: UUID, **kwargs: Any) -> Response:
        caller = self._caller(request)
        _require_scopes(
            request,
            api.diff_read_scopes(
                team_id=self.team.id, stack_name=name, diff_id=diff_id, target_team_id=caller.target_team_id
            ),
        )
        diff = api.get_diff(team_id=self.team.id, stack_name=name, diff_id=diff_id, caller=caller)
        return Response(StackDiffSerializer(diff).data)

    @validated_request(
        request_serializer=PushRequestSerializer,
        responses={202: OpenApiResponse(response=StackDiffSerializer), **_ERRORS},
        summary="Push a diff",
        operation_id="stacks_diff_push",
        description="Push exactly this saved diff. Refused with `stack_moved` when the stack changed since the "
        "diff was made. Returns at once with status `running`. Needs the read and write scopes of every kind the "
        "push touches.",
    )
    @action(detail=True, methods=["post"], url_path=r"diffs/(?P<diff_id>[^/.]+)/push", required_scopes=["stack:write"])
    def push(self, request: ValidatedRequest, name: str, diff_id: UUID, **kwargs: Any) -> Response:
        caller = self._caller(request)
        scopes = api.push_scopes(
            team_id=self.team.id, stack_name=name, diff_id=diff_id, target_team_id=caller.target_team_id
        )
        _require_scopes(request, scopes)
        diff = api.start_push(
            StartPushInput(
                team_id=self.team.id,
                stack_name=name,
                diff_id=diff_id,
                caller=caller,
                max_removals=request.validated_data.get("max_removals"),
            ),
            scopes=scopes,
        )
        return Response(StackDiffSerializer(diff).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        request_serializer=ReconcileRequestSerializer,
        responses={200: OpenApiResponse(response=ReconciledSerializer), **_ERRORS},
        summary="Reconcile after an uncertain push",
        operation_id="stacks_reconcile",
        description="After a push stopped without a known outcome, accept a ready diff computed since then, with "
        "its warnings about entities the push may already have created. Adopt those first if they should not be "
        "created again. The stack can push again afterwards.",
    )
    @action(detail=True, methods=["post"], url_path="reconcile", required_scopes=["stack:write"])
    def reconcile(self, request: ValidatedRequest, name: str, **kwargs: Any) -> Response:
        reconciled = api.reconcile(
            ReconcileInput(
                team_id=self.team.id,
                stack_name=name,
                diff_id=request.validated_data["diff_id"],
                caller=self._caller(request),
            )
        )
        return Response(ReconciledSerializer(reconciled).data)

    @validated_request(
        responses={200: OpenApiResponse(response=BindingSerializer(many=True)), **_ERRORS},
        summary="List a stack's bindings",
        operation_id="stacks_bindings_list",
        description="Each entity the stack manages or has adopted, one page per call.",
    )
    @action(
        detail=True, methods=["get"], url_path="bindings", url_name="stack_bindings", required_scopes=["stack:read"]
    )
    def bindings(self, request: Request, name: str, **kwargs: Any) -> Response:
        return facade_page_response(
            self,
            lambda page: api.list_bindings(team_id=self.team.id, stack_name=name, page=page).map(self._binding_payload),
            serializer_class=BindingSerializer,
        )

    @validated_request(
        request_serializer=AdoptRequestSerializer,
        responses={200: OpenApiResponse(response=AdoptResponseSerializer), **_ERRORS},
        summary="Adopt existing entities",
        operation_id="stacks_adopt",
        description="Record pending bindings, so the next push binds these entities and creates nothing. Each "
        "entity must exist and be one you can edit. Needs the write scopes of each kind.",
    )
    @action(detail=True, methods=["post"], url_path="adopt", required_scopes=["stack:write"])
    def adopt(self, request: ValidatedRequest, name: str, **kwargs: Any) -> Response:
        caller = self._caller(request)
        resources = [AdoptResource(**resource) for resource in request.validated_data["resources"]]
        _require_scopes(request, api.kind_write_scopes(resource.kind for resource in resources))
        bindings = api.adopt(AdoptInput(team_id=self.team.id, stack_name=name, caller=caller, resources=resources))
        payload = {"bindings": [self._binding_payload(binding) for binding in bindings]}
        return Response(AdoptResponseSerializer(payload).data)

    @validated_request(
        responses={200: OpenApiResponse(response=BindingSerializer), **_ERRORS},
        summary="Detach an entity",
        operation_id="stacks_binding_detach",
        description="Release the entity to the UI. The stack no longer manages it, and nothing is deleted. Needs "
        "the write scopes of the entity's kind.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"bindings/(?P<binding_id>[^/.]+)/detach",
        required_scopes=["stack:write"],
    )
    def detach(self, request: Request, name: str, binding_id: UUID, **kwargs: Any) -> Response:
        self._caller(request)
        kind = api.binding_kind(team_id=self.team.id, stack_name=name, binding_id=binding_id)
        _require_scopes(request, api.kind_write_scopes([kind]))
        binding = api.detach(team_id=self.team.id, stack_name=name, binding_id=binding_id)
        return Response(BindingSerializer(self._binding_payload(binding)).data)

    @validated_request(
        request_serializer=SecretWriteSerializer,
        responses={200: OpenApiResponse(response=SecretSerializer), **_ERRORS},
        summary="Set a secret",
        operation_id="stacks_secret_set",
        description="Set or replace the value a definition names with `secret('NAME')`. The value is encrypted and "
        "never returned. Creates the stack if it does not exist yet.",
    )
    @action(
        detail=True,
        methods=["put"],
        url_path=r"secrets/(?P<secret_name>[A-Za-z_][A-Za-z0-9_]*)",
        url_name="stack_secret",
        required_scopes=["stack:write"],
    )
    def secret(self, request: ValidatedRequest, name: str, secret_name: str, **kwargs: Any) -> Response:
        secret = api.set_secret(
            SetSecretInput(
                team_id=self.team.id,
                stack_name=name,
                name=secret_name,
                value=request.validated_data["value"],
                caller=self._caller(request),
            )
        )
        return Response(SecretSerializer(secret).data)

    @validated_request(
        responses={204: None, **_ERRORS},
        summary="Remove a secret",
        operation_id="stacks_secret_remove",
        description="Remove a secret from the stack. A diff that still names it fails with `secret_missing`.",
    )
    @secret.mapping.delete
    def remove_secret(self, request: Request, name: str, secret_name: str, **kwargs: Any) -> Response:
        api.delete_secret(team_id=self.team.id, stack_name=name, name=secret_name)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        responses={200: OpenApiResponse(response=SecretListSerializer), **_ERRORS},
        summary="List secrets",
        operation_id="stacks_secrets_list",
        description="The names of the stack's secrets and when each was last set. Never their values.",
    )
    @action(detail=True, methods=["get"], url_path="secrets", required_scopes=["stack:read"], pagination_class=None)
    def secrets(self, request: Request, name: str, **kwargs: Any) -> Response:
        return Response(SecretListSerializer({"results": api.list_secrets(team_id=self.team.id, stack_name=name)}).data)

    @validated_request(
        query_serializer=AdoptableQuerySerializer,
        responses={200: OpenApiResponse(response=AdoptablePageSerializer), **_ERRORS},
        summary="List adoptable entities",
        operation_id="stacks_adoptable_list",
        description="Entities of one kind that no stack manages and that you can read, with bodies in description "
        "shape. Follow `next` for the next page. Needs the read scopes of the kind.",
    )
    @action(detail=False, methods=["get"], url_path="adoptable", required_scopes=["stack:read"], pagination_class=None)
    def adoptable(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        query = request.validated_query_data
        kind = query["kind"]
        _require_scopes(request, api.kind_read_scopes([kind]))
        page = api.list_adoptable(
            team_id=self.team.id,
            caller=self._caller(request),
            kind=kind,
            cursor=query.get("cursor"),
            limit=query["limit"],
        )
        next_url = (
            request.build_absolute_uri(request.path)
            + "?"
            + urlencode({"kind": kind, "cursor": page.next_cursor, "limit": query["limit"]})
            if page.next_cursor
            else None
        )
        payload = {
            "count": None,
            "next": next_url,
            "previous": None,
            "results": [AdoptableEntitySerializer(item).data for item in page.results],
        }
        return Response(AdoptablePageSerializer(payload).data)

    @validated_request(
        query_serializer=BindingLookupQuerySerializer,
        responses={200: OpenApiResponse(response=BindingLookupSerializer), **_ERRORS},
        summary="Find what manages an entity",
        operation_id="stacks_binding_lookup",
        description="The binding that manages this entity, or null when no stack does.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="bindings",
        url_name="binding_lookup",
        required_scopes=["stack:read"],
        pagination_class=None,
    )
    def binding_lookup(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        query = request.validated_query_data
        found = api.find_bindings(team_id=self.team.id, kind=query["kind"], entity_id=query["entity_id"])
        payload = {"binding": self._binding_payload(found[0]) if found else None}
        return Response(BindingLookupSerializer(payload).data)

    @validated_request(
        request_serializer=ContextPagesRequestSerializer,
        responses={200: OpenApiResponse(response=StackSettingsSerializer), **_ERRORS},
        summary="Let a stack manage context pages",
        operation_id="stacks_context_pages_set",
        description="Turn context pages on or off for this stack. Context pages belong to the organization's one "
        "wiki, so only an organization admin can turn this on. Off by default.",
    )
    @action(detail=True, methods=["post"], url_path="context_pages", required_scopes=["stack:write"])
    def context_pages(self, request: ValidatedRequest, name: str, **kwargs: Any) -> Response:
        settings_ = api.set_context_pages(
            team_id=self.team.id,
            stack_name=name,
            enabled=request.validated_data["enabled"],
            caller=self._caller(request),
        )
        return Response(StackSettingsSerializer(settings_).data)

    @validated_request(
        responses={200: OpenApiResponse(response=ManagedKindListSerializer), **_ERRORS},
        summary="List the kinds managed in code",
        operation_id="stacks_managed_kinds_list",
        description="Each kind of entity some stack in this project manages, with the stack and its repository. "
        "Before creating an entity of a listed kind, add its definition in that repository instead.",
    )
    @action(
        detail=False, methods=["get"], url_path="managed_kinds", required_scopes=["stack:read"], pagination_class=None
    )
    def managed_kinds(self, request: Request, **kwargs: Any) -> Response:
        return Response(ManagedKindListSerializer({"results": api.managed_kinds(team_id=self.team.id)}).data)

    @validated_request(
        request_serializer=GenerateModuleRequestSerializer,
        responses={200: OpenApiResponse(response=GeneratedModuleSerializer), **_ERRORS},
        summary="Generate a typed module",
        operation_id="stacks_module_generate",
        description="The typed module for one language that the events of a stack description give. Nothing is "
        "stored and no stack is created.",
    )
    @action(detail=False, methods=["post"], url_path="modules", required_scopes=["stack:read"], pagination_class=None)
    def modules(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        module = api.generate_module(description=data["description"], language=data["language"])
        return Response(GeneratedModuleSerializer(module).data)

    @validated_request(
        request_serializer=StackChangeRequestSerializer,
        responses={201: OpenApiResponse(response=StartedChangeRequestSerializer), **_ERRORS},
        summary="Ask for a change in code",
        operation_id="stacks_change_request_create",
        description="Start a cloud task that edits this entity's definition in the stack's repository and opens a "
        "pull request. Nothing in PostHog changes until that pull request is merged and pushed.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"bindings/(?P<binding_id>[^/.]+)/change_requests",
        required_scopes=["stack:write", "task:write"],
    )
    def change_requests(self, request: ValidatedRequest, name: str, binding_id: UUID, **kwargs: Any) -> Response:
        data = request.validated_data
        started = api.request_change(
            ChangeRequestInput(
                team_id=self.team.id,
                stack_name=name,
                binding_id=binding_id,
                caller=self._caller(request),
                note=data["note"],
                changes=[RequestedChange(path=change["path"], value=change["value"]) for change in data["changes"]],
            )
        )
        return Response(StartedChangeRequestSerializer(started).data, status=status.HTTP_201_CREATED)
