"""Feature flag facade: gated flag writes for other products.

Every write routes through ``FeatureFlagSerializer`` — the only path that honors
``@approval_gate``, validation, and activity logging. Consumers (experiments, scheduled
changes, MCP tools) call these functions instead of driving the serializer and its DRF
context by hand.

Approval-gate ordering constraint for callers: a gated write can raise ``ApprovalRequired``
(surfacing as a 409 + change_request_id), which conflicts with ``transaction.atomic`` — the
exception propagating out of an atomic block would roll back the just-created pending
ChangeRequest. Run gated writes before/outside any transaction wrapping your own state.
"""

from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.approvals.backend.policies import PolicyEngine
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class _ServiceRequest:
    """Minimal request-like object for DRF serializers used from a service layer.

    Provides the subset of the DRF Request interface that FeatureFlagSerializer
    actually uses, without DRF's authentication machinery.
    """

    def __init__(self, user: Any):
        self.user = user
        self.method = "POST"
        self.path = "/"
        self.data: dict = {}
        self.GET: dict = {}
        self.META: dict = {}
        self.headers: dict = {}
        self.session: dict = {}


def _serializer_context(team: Team, user: Any, request: Any | None) -> dict:
    """Build the DRF serializer context for a gated flag write.

    Callers without a real request (internal service paths) fall back to a minimal
    request shim carrying the acting user — FeatureFlagSerializer needs request.user.

    Pass BOTH get_team and get_organization so the approval gate resolves the policy
    from context rather than falling back to instance derivation.
    """
    flag_request = request if getattr(request, "user", None) is not None else _ServiceRequest(user)
    return {
        "request": flag_request,
        "team_id": team.id,
        "project_id": team.project_id,
        "get_team": lambda: team,
        "get_organization": lambda: team.organization,
    }


def create_flag(data: dict, *, team: Team, user: Any, request: Any | None = None) -> FeatureFlag:
    """Gated create: routes through FeatureFlagSerializer so @approval_gate, validation,
    and activity logging apply. ``data`` is the flag's own write shape (key, name, filters,
    active, ...) and is applied as-is — nothing is silently dropped. Raises ApprovalRequired
    when a policy requires approval."""
    serializer = FeatureFlagSerializer(data=data, context=_serializer_context(team, user, request))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def update_flag(flag: FeatureFlag, data: dict, *, team: Team, user: Any, request: Any | None = None) -> FeatureFlag:
    """Gated partial update: routes through FeatureFlagSerializer so @approval_gate,
    validation, and activity logging apply. ``data`` is a partial flag write payload
    (fields it omits are untouched) applied as-is — nothing is silently dropped.
    Raises ApprovalRequired when a policy requires approval; the flag is left untouched."""
    serializer = FeatureFlagSerializer(flag, data=data, partial=True, context=_serializer_context(team, user, request))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def set_flag_active(
    flag: FeatureFlag, active: bool, *, team: Team, user: Any, request: Any | None = None
) -> FeatureFlag:
    """Flip a flag's active state THROUGH the approval gate.

    Routing the flip through FeatureFlagSerializer.update() honours the
    @approval_gate so the feature_flag.enable/disable policies apply. Raises
    ApprovalRequired (which surfaces as a 409 + change_request_id) when a
    policy requires approval; in that case the flag is left untouched.

    The gate's detect()/extract_intent() read the serializer's validated_data
    (the actual change being saved), so an incoming HTTP request that triggered
    the flip is passed straight through — no synthetic PATCH request is needed.
    """
    return update_flag(flag, {"active": active}, team=team, user=user, request=request)


def archive_flag(
    flag: FeatureFlag,
    *,
    team: Team,
    user: Any,
    request: Any | None = None,
    disable_if_active: bool = False,
) -> FeatureFlag:
    """Archive a flag through the gated serializer path.

    An archived flag must be disabled (the serializer enforces it); pass
    ``disable_if_active`` to disable an active flag in the same write. Disabling
    applies the dependents guard (``raise_if_flag_has_dependents``) inside the
    serializer, and trips the feature_flag.disable approval policy if one is
    enabled — check ``flag_disable_requires_approval`` first when the caller
    cannot surface a change request.
    """
    data: dict[str, Any] = {"archived": True}
    if disable_if_active and flag.active:
        data["active"] = False
    return update_flag(flag, data, team=team, user=user, request=request)


def unarchive_flag(flag: FeatureFlag, *, team: Team, user: Any, request: Any | None = None) -> FeatureFlag:
    """Unarchive a flag through the gated serializer path.

    The flag stays disabled; re-enabling it is a separate, explicit write
    (``set_flag_active``).
    """
    return update_flag(flag, {"archived": False}, team=team, user=user, request=request)


def user_can_edit_flag(flag: FeatureFlag, *, team: Team, user: Any) -> bool:
    """Whether ``user`` has editor access to this flag — the same check the feature flag API enforces."""
    if not isinstance(user, User) or user.is_anonymous:
        return False
    return UserAccessControl(user=user, team=team).check_access_level_for_object(flag, "editor")


def flag_disable_requires_approval(team: Team) -> bool:
    """Whether an enabled approval policy gates disabling a flag for this team/org."""
    policy = PolicyEngine().get_policy(action_key="feature_flag.disable", team=team, organization=team.organization)
    return policy is not None


def serialize_flags(flags: Any, *, context: dict) -> Any:
    """The flag API's full list representation for the given flags.

    ``context`` is the caller's DRF serializer context (a viewset's
    ``get_serializer_context()``): the representation includes request- and
    access-control-derived fields, so it can only be built for a real request.
    """
    return FeatureFlagSerializer(flags, many=True, context=context).data
