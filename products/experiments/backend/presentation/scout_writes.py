"""Rules a Signals scout's experiment writes must clear, on top of the scopes its token carries.

A person grants one scout `experiment:write` from the scout's settings, and that grant is
deliberately narrower than the scope object. It excludes deletion, copying to another project,
migration, flag cleanup pull requests, and any change to a live flag's rollout without
`feature_flag:write`. None of these can be expressed in the token, because one scope object covers
the whole experiment surface, so they are enforced here.

Every rule applies to scout sandbox callers alone (`is_scout_sandbox_request`), so a person working
in the app or a personal API key sees no change.
"""

from collections.abc import Collection, Mapping
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

DELETE_REFUSED = "Scouts cannot delete experiments. End the experiment, then archive it to hide it from the list."

COPY_TO_PROJECT_REFUSED = (
    "Scouts cannot copy an experiment to another project, because a scout works only in its own project. "
    "Use `duplicate` to make a draft copy in this project."
)

MIGRATE_REFUSED = (
    "Scouts cannot migrate a legacy experiment, because migration also creates shared metrics. "
    "Say in your report that this experiment needs a person to migrate it."
)

CLEANUP_PR_REFUSED = (
    "Scouts cannot open a flag cleanup pull request. Leave `open_cleanup_pr` off, and say in your report "
    "that the flag code is ready to remove."
)

SHIP_VARIANT_NEEDS_FLAG_WRITE = (
    "Shipping a variant rewrites the rollout of the experiment's feature flag, so a scout needs "
    "`feature_flag:write` as well as `experiment:write`. End the experiment with `end` instead, and say "
    "in your report which variant a person should ship."
)

LIVE_FLAG_CONFIG_NEEDS_FLAG_WRITE = (
    "This experiment has launched or its feature flag is already on, so changing its variants, rollout, "
    "or holdout changes what users see. A scout needs `feature_flag:write` for that. Say in your report "
    "which change a person should make."
)


def is_true(value: Any) -> bool:
    """Read a raw request value the way `BooleanField` does, without raising on an unhashable value."""
    return isinstance(value, bool | int | str) and value in serializers.BooleanField.TRUE_VALUES


def update_carries_flag_config(data: Mapping[str, Any], *, legacy_flag_config_keys: Collection[str]) -> bool:
    """Whether an experiment update can write the linked flag's variants, rollout, or holdout.

    The flag config arrives as the `feature_flag` object or, for legacy callers, as keys under
    `parameters`. The serializer copies the legacy keys onto the same flag write. A holdout arrives
    as `holdout_id`, because the `holdout` field is read-only.
    """
    parameters = data.get("parameters")
    legacy_flag_keys = isinstance(parameters, Mapping) and any(key in parameters for key in legacy_flag_config_keys)
    return "feature_flag" in data or "holdout_id" in data or legacy_flag_keys


def refuse_scout_experiment_delete(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(DELETE_REFUSED)


def refuse_scout_experiment_copy_to_project(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(COPY_TO_PROJECT_REFUSED)


def refuse_scout_experiment_migrate(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(MIGRATE_REFUSED)


def refuse_scout_cleanup_pr(is_scout_caller: bool, *, open_cleanup_pr: bool) -> None:
    """Refuse a scout's request to open a flag cleanup pull request.

    Every scout token carries `task:write` through `INTERNAL_SCOPES`, so the `task:write` check in
    `dangerously_get_required_scopes` does not stop a scout. A cleanup task changes a repository and
    opens a pull request, which the experiment grant does not tell a person about.
    """
    if is_scout_caller and open_cleanup_pr:
        raise PermissionDenied(CLEANUP_PR_REFUSED)


def refuse_scout_ship_variant_without_flag_write(is_scout_caller: bool, *, can_write_feature_flag: bool) -> None:
    """Refuse a scout's ship unless its token also carries `feature_flag:write`.

    Launch and pause also change the flag's active state, but only `ship_variant` changes which
    variant users get, and a ship can roll that variant out to everyone. `feature_flag:write` is not
    grantable to a scout yet, so in practice a scout ends an experiment and a person ships it.
    """
    if is_scout_caller and not can_write_feature_flag:
        raise PermissionDenied(SHIP_VARIANT_NEEDS_FLAG_WRITE)


def refuse_scout_live_flag_config_change(
    is_scout_caller: bool, *, can_write_feature_flag: bool, flag_is_live: bool
) -> None:
    """Refuse a scout's update that rewrites a live flag's variants, rollout, or holdout.

    An update with `update_feature_flag_params` can set one variant to 100%, which is a ship by
    another route. A flag counts as live once the experiment has launched, because a paused
    experiment resumes with the edited rollout. A draft counts as live too when it reuses a flag
    that is already on. A draft on its own new flag reaches no user until launch, so a scout can
    still set up its variants.
    """
    if is_scout_caller and not can_write_feature_flag and flag_is_live:
        raise PermissionDenied(LIVE_FLAG_CONFIG_NEEDS_FLAG_WRITE)
