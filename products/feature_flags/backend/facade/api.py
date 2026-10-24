"""Feature flag facade: gated flag writes and read helpers for other products.

Every write routes through ``FeatureFlagSerializer`` — the only path that honors
``@approval_gate``, validation, and activity logging. Consumers (currently experiments)
call these functions instead of driving the serializer and its DRF context by hand.
``clear_feature_enrollment`` falls back to a raw model write when the serializer rejects
a flag's stored config version 1 filters, because enrollment cleanup must never fail.
The read helpers (``user_can_edit_flag``, ``user_can_create_flags``, ``flag_disable_requires_approval``,
``serialize_flags``, ``get_feature_flag_request_usage``) expose the flag API's
access-control, approval-policy, representation, and request-usage logic behind
the same boundary.

Writes do not enforce access control — that lives at the viewset layer. A caller
acting on behalf of an end user must pre-check ``user_can_edit_flag`` before writing an
existing flag, and ``user_can_create_flags`` before creating one. ``set_condition_rollout`` is
the exception: it takes the acting user's id and runs the editor check itself.

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

from datetime import datetime
from typing import Any, Literal

from django.db import transaction

import structlog
from rest_framework.exceptions import ValidationError

from posthog.api.utils import ServiceRequest
from posthog.dataclasses import frozen
from posthog.exceptions import Conflict
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.approvals.backend.exceptions import ApprovalRequired, PolicyConflict
from products.approvals.backend.policies import PolicyEngine
from products.feature_flags.backend.api.feature_flag import (
    FeatureFlagSerializer,
    flag_version_conflict_message,
    validate_stored_cohort_references as _validate_stored_cohort_references,
)
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE
from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.filters import (
    set_feature_enrollment,
    set_release_condition_rollout as _set_release_condition_rollout,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.request_usage import (
    FeatureFlagRequestType as FeatureFlagRequestType,
    FeatureFlagRequestUsage as FeatureFlagRequestUsage,
    query_feature_flag_request_usage,
)

logger = structlog.get_logger(__name__)


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


def create_flag(
    data: dict,
    *,
    team: Team,
    user: Any,
    request: Any | None = None,
    serializer_context: dict | None = None,
) -> FeatureFlag:
    """Gated create: routes through FeatureFlagSerializer so @approval_gate, validation,
    and activity logging apply. ``data`` is the flag's own write shape (key, name, filters,
    active, ...) and is applied as-is — nothing is silently dropped. Raises ApprovalRequired
    when a policy requires approval. ``user=None`` is a system write (see module docstring):
    ``created_by`` stays null, activity is logged as system, the approval gate is skipped.
    ``serializer_context`` is extra serializer context (an HTTP caller passes its viewset
    context); the facade's own ``request``, ``team_id``, ``project_id``, ``get_team`` and
    ``get_organization`` entries win over the caller's."""
    context = {**(serializer_context or {}), **_serializer_context(team, user, request)}
    serializer = FeatureFlagSerializer(data=data, context=context)
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def _redact_unchanged_encrypted_payloads(flag: FeatureFlag, data: dict) -> dict:
    """Facade callers derive update filters from ``flag.get_filters()``, which stores
    encrypted payload values as ciphertext. Ciphertext echoed back through the serializer
    fails its JSON payload validation (and must never be re-encrypted), so values
    byte-identical to the stored ones are swapped for the redacted placeholder, which the
    serializer preserves. Genuinely new payload values pass through and are encrypted."""
    if not isinstance(data, dict) or detect_config_format(flag.filters).kind != "v1":
        return data
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


def update_flag(
    flag: FeatureFlag,
    data: dict,
    *,
    team: Team,
    user: Any,
    request: Any | None = None,
    partial: bool = True,
    serializer_context: dict | None = None,
) -> FeatureFlag:
    """Gated update: routes through FeatureFlagSerializer so @approval_gate,
    validation, and activity logging apply. ``data`` is a flag write payload applied
    as-is — nothing is silently dropped. Raises ApprovalRequired when a policy requires
    approval; the flag is left untouched. ``user=None`` is a system write (see module
    docstring): ``last_modified_by`` is cleared, activity is logged as system, the
    approval gate is skipped.

    ``partial=True`` (the default) leaves omitted fields untouched; ``partial=False`` is
    the PUT shape, where the serializer enforces its required fields. ``serializer_context``
    is extra serializer context (an HTTP caller passes its viewset context); the facade's own
    ``request``, ``team_id``, ``project_id``, ``get_team`` and ``get_organization`` entries
    win over the caller's.

    Encrypted payload values carried over unchanged from ``flag.get_filters()`` are
    preserved as-is, never re-validated or re-encrypted."""
    data = _redact_unchanged_encrypted_payloads(flag, data)
    context = {**(serializer_context or {}), **_serializer_context(team, user, request, method="PATCH")}
    serializer = FeatureFlagSerializer(flag, data=data, partial=partial, context=context)
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
    (``set_flag_active``). Raises ``ValidationError`` when a release condition targets a
    deleted cohort.
    """
    return update_flag(flag, {"archived": False}, team=team, user=user, request=request)


def validate_flag_restorable(flag_id: int, *, team_id: int) -> None:
    """Raise ``ValidationError`` when a release condition targets a missing or deleted cohort.

    A restored flag with such a condition fails every evaluation that reaches it. ``update_flag`` runs this
    check on a restore. A caller that restores a flag another way must run it first. A
    hard-deleted id or another team's flag has nothing to check.
    """
    flag = FeatureFlag.objects_including_soft_deleted.filter(pk=flag_id, team_id=team_id).first()
    if flag is not None:
        _validate_stored_cohort_references(flag)


def clear_feature_enrollment(flag_id: int, *, team: Team) -> None:
    """Clear the enrollment marker on an early access feature's linked flag (feature demoted or deleted).

    Cleanup must never fail: a linked flag can hold stored filter shapes the current
    FeatureFlagSerializer rejects or crashes on (group-aggregated conditions, malformed
    legacy properties, ...), and a rejection here would make the feature undeletable.
    Prefer the gated facade write (validation, activity logging); fall back to a raw
    model write when it raises. This is a system write (user=None): an enabled approval
    policy must never block cleanup with a 409, and activity is logged as system.

    Another config format raises ``ConfigFormatError`` from ``set_feature_enrollment`` before
    either write. No caller reaches it: an early access feature only links config version 1 flags.

    The early return covers a hard-deleted id or another team's flag, so nothing is left to
    clear. A soft-deleted flag still gets cleared, through ``objects_including_soft_deleted``:
    the default manager hides it, and skipping it would leave the marker to come back with the
    flag on a restore.
    """
    flag = FeatureFlag.objects_including_soft_deleted.filter(pk=flag_id, team=team).first()
    if flag is None:
        return

    cleared_filters = set_feature_enrollment(flag.get_filters() or {}, None)
    # Without "groups", the serializer's partial-PATCH shortcut discards the incoming
    # filters and returns the stored ones — silently skipping the cleanup entirely.
    if "groups" in cleared_filters:
        try:
            update_flag(flag, {"filters": cleared_filters}, team=team, user=None)
            return
        except Exception as exc:
            # Stored legacy JSON can raise arbitrary exception types through the flag
            # validator (ValidationError, TypeError, KeyError, ...), so catch broadly.
            logger.warning(
                "early_access_feature_enrollment_cleanup_fell_back_to_raw_write",
                feature_flag_id=flag.id,
                error=str(exc),
            )
    flag.filters = cleared_filters  # nosemgrep: feature-flags-no-raw-filters-access -- deliberate never-fail cleanup fallback when the gated write can't validate stored legacy filter shapes
    flag.save(update_fields=["filters"])


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

    new_filters = {
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
    # A holdout must keep excluding its users after the winner ships — that is its
    # entire purpose (measuring shipped features against an unexposed baseline).
    if current_filters.get("holdout"):
        new_filters["holdout"] = current_filters["holdout"]
    return new_filters


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


def user_can_create_flags(*, team: Team, user: User) -> bool:
    """Whether ``user`` may create a flag in this team — the resource-level counterpart of
    ``user_can_edit_flag``, and the same check the feature flag API enforces on create.

    A product that creates a flag as a side effect of its own write needs this, because the
    write goes through ``create_flag``, which enforces no access control. Without it, editor
    access to that product substitutes for flag access. Unlike ``user_can_edit_flag`` this takes
    a real ``User``, so a caller holding an unknown principal narrows it before asking."""
    return UserAccessControl(user=user, team=team).check_access_level_for_resource("feature_flag", "editor")


class FlagNotFound(Exception):
    """No flag with that id or key exists in the project, or it is deleted."""


class FlagAccessDenied(Exception):
    """The acting user cannot edit the flag."""


class FlagVersionConflict(Exception):
    """The flag changed after the version the caller read. Nothing was written."""


class FlagRolloutRejected(Exception):
    """The rollout change does not apply to this flag (no such condition, or an unsupported config format)."""


class FlagChangePolicyConflict(Exception):
    """The change matches more than one approval policy, so it cannot be gated as one change request."""

    def __init__(self, message: str, *, guidance: str, conflicting_policies: list) -> None:
        super().__init__(message)
        self.guidance = guidance
        self.conflicting_policies = conflicting_policies


class FlagChangeNeedsApproval(Exception):
    """An approval policy gates the change. A change request was filed and the flag is left untouched."""

    def __init__(self, message: str, *, change_request_id: str) -> None:
        super().__init__(message)
        self.change_request_id = change_request_id


@frozen
class ConditionRolloutResult:
    flag_id: int
    flag_key: str
    version: int
    condition_index: int
    rollout_percentage: int | float
    changed: bool


class _RolloutServiceRequest(ServiceRequest):
    """The request shim for a rollout write from service code.

    ``strict_version_precondition`` makes ``FeatureFlagSerializer`` refuse the write under its row
    lock when ``version`` is not current, the same as the flag API's rollout actions. A
    release-condition index only names the condition the caller read, so any change since that
    version must refuse the write.
    """

    strict_version_precondition = True
    skip_opportunistic_filter_cleanup = True

    def __init__(self, user: User, *, version: int) -> None:
        super().__init__(user, method="PATCH")
        self.data = {"version": version}


def set_condition_rollout(
    *,
    team_id: int,
    user_id: int,
    flag_id: int | None,
    flag_key: str | None,
    condition_index: int,
    rollout_percentage: int | float,
    version: int | None,
) -> ConditionRolloutResult:
    """Set ``rollout_percentage`` on one release condition of a flag, as ``user_id``.

    This is the service-code counterpart of the flag API's ``set_release_condition_rollout``
    action. It checks the same editor access as the flag API, then writes through
    ``update_flag``, so validation, versioning, activity logging and cache updates apply. Only
    ``filters.groups[condition_index].rollout_percentage`` changes.

    ``version`` is the flag version the caller read. ``None`` means a flag written before
    versioning and reads as 0. Pass the flag by ``flag_id`` or ``flag_key``; the id wins when
    both are set. Raises ``FlagNotFound``, ``FlagAccessDenied``, ``FlagVersionConflict``,
    ``FlagRolloutRejected`` or ``FlagChangeNeedsApproval``.
    """
    if condition_index < 0:
        raise FlagRolloutRejected("The release condition index must be 0 or more.")
    if not 0 <= rollout_percentage <= 100:
        raise FlagRolloutRejected("The rollout percentage must be between 0 and 100.")

    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    flags = FeatureFlag.objects.filter(team_id=team.id)
    flag = flags.filter(id=flag_id).first() if flag_id is not None else flags.filter(key=flag_key).first()
    if flag is None:
        raise FlagNotFound(f"Feature flag {flag_id if flag_id is not None else flag_key} is not in this project.")
    if not user_can_edit_flag(flag, team=team, user=user):
        # Generic on purpose: a caller probing ids must not learn a restricted flag's key.
        raise FlagAccessDenied("You do not have editor access to this feature flag.")
    if detect_config_format(flag.filters).kind != "v1":
        raise FlagRolloutRejected("This flag uses a configuration format that rollout changes cannot modify yet.")

    expected_version = version or 0
    # A fast path ahead of the approval gate, so a stale caller never files a change request
    # for a write the serializer would then refuse under its row lock.
    if (flag.version or 0) != expected_version:
        raise FlagVersionConflict(flag_version_conflict_message(expected_version, flag.version or 0))

    with transaction.atomic():
        # Decide against the locked row, so an edit landing after the read above cannot make
        # the change look already applied.
        locked = FeatureFlag.objects_including_soft_deleted.select_for_update().get(pk=flag.pk)
        if locked.deleted:
            raise FlagNotFound(f"Feature flag {locked.key} is not in this project.")
        if (locked.version or 0) != expected_version:
            raise FlagVersionConflict(flag_version_conflict_message(expected_version, locked.version or 0))
        try:
            new_filters = _set_release_condition_rollout(locked.get_filters(), condition_index, rollout_percentage)
        except IndexError:
            condition_count = len(locked.conditions)
            if condition_count:
                raise FlagRolloutRejected(
                    f"Feature flag {locked.key} has no release condition at index {condition_index}. It has "
                    f"{condition_count}, so the valid indexes are 0 through {condition_count - 1}."
                )
            raise FlagRolloutRejected(f"Feature flag {locked.key} has no release conditions.")

    saved = locked
    # Only this condition's stored value can differ; an absent value is not the same as 100.
    changed = locked.conditions[condition_index].get("rollout_percentage") != rollout_percentage
    # The write runs outside the transaction above: the approval gate files a change request
    # and then raises, and a rollback would discard that request. The serializer takes the row
    # lock again and repeats the version check.
    if changed:
        try:
            saved = update_flag(
                locked,
                {"filters": new_filters},
                team=team,
                user=user,
                request=_RolloutServiceRequest(user, version=expected_version),
            )
        except Conflict as error:
            raise FlagVersionConflict(str(error.detail)) from error
        except ApprovalRequired as error:
            raise FlagChangeNeedsApproval(error.message, change_request_id=str(error.change_request.id)) from error
        except PolicyConflict as error:
            raise FlagChangePolicyConflict(
                error.message, guidance=error.guidance, conflicting_policies=error.conflicting_policies
            ) from error

    return ConditionRolloutResult(
        flag_id=saved.id,
        flag_key=saved.key,
        version=saved.version or 0,
        condition_index=condition_index,
        rollout_percentage=rollout_percentage,
        changed=changed,
    )


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


def get_feature_flag_request_usage(
    *, team_id: int, date_from: datetime, date_to: datetime, time_interval: Literal["hour", "day"]
) -> list[FeatureFlagRequestUsage]:
    return query_feature_flag_request_usage(
        team_id=team_id, date_from=date_from, date_to=date_to, time_interval=time_interval
    )


def flag_is_active(key: str, *, team_id: int | None = None) -> bool:
    """Whether an active flag with this key exists, optionally narrowed to one team.

    A direct row read, not an evaluation: it ignores rollout percentages and release
    conditions. Callers use it as a local-development fallback for when the analytics SDK
    is disabled and ``posthoganalytics.feature_enabled`` cannot answer.
    """
    qs = FeatureFlag.objects.filter(key=key, active=True)
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    return qs.exists()
