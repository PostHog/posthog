"""Feature flag facade: gated flag writes and read helpers for other products.

Every write routes through ``FeatureFlagSerializer`` — the only path that honors
``@approval_gate``, validation, and activity logging. Consumers (currently experiments)
call these functions instead of driving the serializer and its DRF context by hand.
The read helpers (``user_can_edit_flag``, ``flag_disable_requires_approval``,
``serialize_flags``) expose the flag API's access-control, approval-policy, and
representation logic behind the same boundary.

Writes do not enforce access control — that lives at the viewset layer. A caller
acting on behalf of an end user must pre-check ``user_can_edit_flag`` first.

Approval-gate ordering constraint for callers: a gated write can raise ``ApprovalRequired``
(surfacing as a 409 + change_request_id), which conflicts with ``transaction.atomic`` — the
exception propagating out of an atomic block would roll back the just-created pending
ChangeRequest. Run gated writes before/outside any transaction wrapping your own state.

System writes: callers with no acting user (beat tasks, service code reacting to
lifecycle events) pass ``user=None``. The write still routes through the serializer
(validation, caches, activity logging — attributed as ``is_system``), but the approval
gate does not engage: the request shim explicitly declares ``is_system=True``, the only
signal the gate skips on (its policies target human-driven changes, and a request-less
caller cannot surface a 409/change request), so ``ApprovalRequired`` is never raised.
"""

from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.api.utils import ServiceRequest
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.approvals.backend.policies import PolicyEngine
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _serializer_context(team: Team, user: Any, request: Any | None, *, method: str = "POST") -> dict:
    """Build the DRF serializer context for a gated flag write.

    Callers without a real request (internal service paths) fall back to a minimal
    request shim carrying the acting user — FeatureFlagSerializer needs request.user.
    ``user=None`` makes this a system write (see module docstring); the shim declares
    it explicitly via ``is_system``, the only signal the approval gate skips on.
    ``method`` is the HTTP method the shim reports — the serializer branches on it
    (create-only validation runs on "POST"), so updates must pass "PATCH". Supplied
    ``ServiceRequest`` shims are rebuilt with it; real HTTP requests pass through
    untouched.

    Pass BOTH get_team and get_organization so the approval gate resolves the policy
    from context rather than falling back to instance derivation.
    """
    request_has_user = getattr(request, "user", None) is not None
    # A user-bearing request would silently override user=None (gate engages, attribution
    # goes to request.user) — reject the contradiction instead.
    if user is None and request_has_user:
        raise ValueError("user=None is a system write; do not pass a user-bearing request with it")
    if isinstance(request, ServiceRequest):
        # Caller-built shims default to POST — align the method with this write.
        request.method = method
    flag_request = request if request_has_user else ServiceRequest(user, is_system=user is None, method=method)
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
    when a policy requires approval. ``user=None`` is a system write (see module docstring):
    ``created_by`` stays null, activity is logged as system, the approval gate is skipped."""
    serializer = FeatureFlagSerializer(data=data, context=_serializer_context(team, user, request))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def _redact_unchanged_encrypted_payloads(flag: FeatureFlag, data: dict) -> dict:
    """Facade callers derive update filters from ``flag.get_filters()``, which stores
    encrypted payload values as ciphertext. Ciphertext echoed back through the serializer
    fails its JSON payload validation (and must never be re-encrypted), so values
    byte-identical to the stored ones are swapped for the redacted placeholder, which the
    serializer preserves. Genuinely new payload values pass through and are encrypted."""
    filters = data.get("filters")
    if not flag.has_encrypted_payloads or not isinstance(filters, dict):
        return data
    stored = (flag.filters or {}).get("payloads") or {}
    incoming = filters.get("payloads")
    if not isinstance(incoming, dict):
        return data
    redacted = {k: REDACTED_PAYLOAD_VALUE if k in stored and v == stored[k] else v for k, v in incoming.items()}
    if redacted == incoming:
        return data
    return {**data, "filters": {**filters, "payloads": redacted}}


def update_flag(flag: FeatureFlag, data: dict, *, team: Team, user: Any, request: Any | None = None) -> FeatureFlag:
    """Gated partial update: routes through FeatureFlagSerializer so @approval_gate,
    validation, and activity logging apply. ``data`` is a partial flag write payload
    (fields it omits are untouched) applied as-is — nothing is silently dropped.
    Raises ApprovalRequired when a policy requires approval; the flag is left untouched.
    ``user=None`` is a system write (see module docstring): ``last_modified_by`` is
    cleared, activity is logged as system, the approval gate is skipped.

    Encrypted payload values carried over unchanged from ``flag.get_filters()`` are
    preserved as-is, never re-validated or re-encrypted."""
    data = _redact_unchanged_encrypted_payloads(flag, data)
    serializer = FeatureFlagSerializer(
        flag, data=data, partial=True, context=_serializer_context(team, user, request, method="PATCH")
    )
    serializer.is_valid(raise_exception=True)
    saved = serializer.save()
    if saved.has_encrypted_payloads:
        # The serializer swaps the saved ciphertext for its response form (redacted or
        # decrypted) on the in-memory instance; reload so a subsequent write of this
        # instance cannot persist the placeholder over the stored ciphertext.
        saved.refresh_from_db(fields=["filters"])
    return saved


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


def _roll_out_variant(
    current_filters: dict,
    variant_key: str,
    *,
    release_to_everyone: bool = False,
    release_condition_description: str | None = None,
) -> dict:
    """Rewrite flag filters so the selected variant gets 100% of the variant distribution.

    When ``release_to_everyone`` is False (default), existing release conditions on
    the flag are preserved untouched: the variant is served only to users who
    already match them, and any per-user variant overrides keep applying.

    When ``release_to_everyone`` is True, a catch-all release condition is prepended
    that rolls the variant out to 100% of users — note that under top-down
    first-match evaluation this overrides any existing release conditions and
    per-user variant overrides below it. ``release_condition_description`` is set as
    the description of that catch-all condition, so callers can say why it was added;
    it has no effect unless ``release_to_everyone`` is True.
    """
    groups = list(current_filters.get("groups", []))
    if release_to_everyone:
        catch_all: dict[str, Any] = {"properties": [], "rollout_percentage": 100}
        if release_condition_description is not None:
            catch_all["description"] = release_condition_description
        groups = [catch_all, *groups]

    return {
        "aggregation_group_type_index": current_filters.get("aggregation_group_type_index"),
        "payloads": current_filters.get("payloads", {}),
        "multivariate": {
            "variants": [
                {
                    "key": v["key"],
                    "rollout_percentage": 100 if v["key"] == variant_key else 0,
                    **({"name": v["name"]} if v.get("name") else {}),
                }
                for v in current_filters.get("multivariate", {}).get("variants", [])
            ],
        },
        "groups": groups,
    }


def ship_variant(
    flag: FeatureFlag,
    variant_key: str,
    *,
    team: Team,
    user: Any,
    request: Any | None = None,
    release_to_everyone: bool = False,
    release_condition_description: str | None = None,
    base_filters: dict | None = None,
) -> FeatureFlag:
    """Roll ``variant_key`` out at 100% of the flag's variant distribution, through the gated write.

    By default (``release_to_everyone=False``) existing release conditions on the flag
    are preserved untouched — the variant is served only to users who already match
    them. Pass ``release_to_everyone=True`` to also prepend a catch-all release
    condition that rolls the variant out to 100% of users (overrides any existing
    release conditions and per-user variant overrides), with
    ``release_condition_description`` as its description — that parameter has no
    effect unless ``release_to_everyone`` is True.

    ``base_filters`` lets a caller fold companion adjustments it already computed from
    the flag's current filters into the same gated write; defaults to the flag's
    current filters. ``variant_key`` is validated against ``base_filters`` (not
    ``flag.filters``), so its ``multivariate.variants`` must match the flag's own.
    The parameter is transitional: it exists so the experiments-side freeze-strip
    folds into a single gated write, and goes away once that strip moves flag-side.

    Raises ValidationError when the variant doesn't exist on the flag, and
    ApprovalRequired when a policy gates the write — the flag is left untouched
    in both cases.
    """
    filters = base_filters if base_filters is not None else (flag.filters or {})

    # Validate variant_key exists on the flag
    variants = filters.get("multivariate", {}).get("variants", [])
    if not any(v["key"] == variant_key for v in variants):
        raise ValidationError(f"Variant '{variant_key}' not found on feature flag.")

    new_filters = _roll_out_variant(
        filters,
        variant_key,
        release_to_everyone=release_to_everyone,
        release_condition_description=release_condition_description,
    )
    return update_flag(flag, {"filters": new_filters}, team=team, user=user, request=request)


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
