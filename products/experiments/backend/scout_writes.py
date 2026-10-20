"""Rules a Signals scout's experiment writes must clear, on top of the scopes its token carries.

A person grants one scout `experiment:write` from the scout's settings, and that grant is
deliberately narrower than the scope object: it excludes deletion, copying to another project, and
shipping a variant without `feature_flag:write`. None of these can be expressed in the token, because
one scope object covers the whole experiment surface, so they are enforced here.

Every rule applies to scout sandbox callers alone (`is_scout_sandbox_request`), so a person working
in the app or a personal API key sees no change.
"""

from rest_framework.exceptions import PermissionDenied

DELETE_REFUSED = "Scouts cannot delete experiments. End the experiment, then archive it to hide it from the list."

COPY_TO_PROJECT_REFUSED = (
    "Scouts cannot copy an experiment to another project, because a scout works only in its own project. "
    "Use `duplicate` to make a draft copy in this project."
)

SHIP_VARIANT_NEEDS_FLAG_WRITE = (
    "Shipping a variant rewrites the rollout of the experiment's feature flag, so a scout needs "
    "`feature_flag:write` as well as `experiment:write`. End the experiment with `end` instead, and say "
    "in your report which variant a person should ship."
)


def refuse_scout_experiment_delete(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(DELETE_REFUSED)


def refuse_scout_experiment_copy_to_project(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(COPY_TO_PROJECT_REFUSED)


def refuse_scout_ship_variant_without_flag_write(is_scout_caller: bool, *, can_write_feature_flag: bool) -> None:
    """Refuse a scout's ship unless its token also carries `feature_flag:write`.

    Launch and pause also change the flag's active state, but only `ship_variant` changes which
    variant users get, and a ship can roll that variant out to everyone. `feature_flag:write` is not
    grantable to a scout yet, so in practice a scout ends an experiment and a person ships it.
    """
    if is_scout_caller and not can_write_feature_flag:
        raise PermissionDenied(SHIP_VARIANT_NEEDS_FLAG_WRITE)
