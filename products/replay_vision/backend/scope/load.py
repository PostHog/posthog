"""Reads a scanner's scope from whichever store currently holds it.

Three stores answer the same question while the migration runs. This is the one place that order is
written down, so a caller never has to know which store a given row uses.
"""

from typing import Any

from pydantic import ValidationError

from products.replay_vision.backend.scope.base import ScopeSource
from products.replay_vision.backend.scope.experiment import ExperimentScope, ExperimentScopeSettings
from products.replay_vision.backend.scope.registry import SCOPES, SETTINGS

# Every store a scanner or snapshot can name its experiment in, in the order `stored_scope` reads
# them. Four readers outside this module ask the same question of a frozen `scanner_snapshot`, in
# three different languages: a Python dict, a Django `Q`, and raw SQL. None can share a function, so
# they share this list instead, and `test_scope.py` fails when a reader hardcodes a subset of it.
#
# `scope` leads because it is the store the others are migrating into. Leaving it out of a reader is
# the mistake this constant exists to stop: a scope-only snapshot then names no experiment, and a
# gate that treats "no experiment" as "unrestricted" hands its rows to a caller denied that
# experiment.
EXPERIMENT_ID_SNAPSHOT_STORES = ("scope", "experiment_targeting", "scanner_config")

# Settings the mirror could not record, because they reached the settings model after the
# `scope` column shipped. A blob the mirror wrote before then carries neither.
_MIRROR_PREDATED_SETTINGS = ("balance", "start_on_launch")


def snapshot_experiment_id(snapshot: dict[str, Any] | None) -> int | None:
    """The experiment a frozen `scanner_snapshot` names, from whichever store holds it.

    For readers that hold a snapshot dict rather than a `ScopeSource`. `scope_for` is the reader for
    anything that needs the whole scope.
    """
    for store in EXPERIMENT_ID_SNAPSHOT_STORES:
        experiment_id = ((snapshot or {}).get(store) or {}).get("experiment_id")
        if experiment_id is not None:
            return experiment_id
    return None


def stored_scope(source: ScopeSource, *, legacy_only: bool = False) -> dict[str, Any] | None:
    """The scope blob for this scanner or snapshot, read in migration order: the `scope` column
    first, then the two stores it replaces.

    Returns the blob rather than a `Scope` so a caller that only needs the experiment id does not
    pay for validation. Use `scope_for` to get the behavior.

    `legacy_only` skips the `scope` column, for the dual write that derives the column from the
    older stores. Without it the mirror would read back the value it wrote and pin a retarget to
    the previous experiment.
    """
    scope = source.scope
    if not legacy_only and isinstance(scope, dict) and scope.get("kind"):
        return _with_settings_the_mirror_predates(source, scope)

    # Neither older store records a kind, because both only ever meant "experiment".
    from products.replay_vision.backend.models.replay_scanner import (  # noqa: PLC0415
        ScannerType,
        config_experiment_scope,
    )

    if source.scanner_type == ScannerType.EXPERIMENT:
        from_config = config_experiment_scope(source.scanner_config)
        if from_config is not None:
            return {"kind": ExperimentScope.kind, **from_config}
        return None

    targeting = source.experiment_targeting
    if isinstance(targeting, dict) and targeting.get("experiment_id") is not None:
        # The legacy column holds a singular `variant`; the scope shape only has the plural, so a
        # single watched variant becomes a one-item list.
        variant = targeting.get("variant")
        variants = targeting.get("variants") or ([variant] if variant else None)
        return {
            "kind": ExperimentScope.kind,
            "experiment_id": targeting["experiment_id"],
            "variants": variants,
        }
    return None


def _with_settings_the_mirror_predates(source: ScopeSource, scope: dict[str, Any]) -> dict[str, Any]:
    """Fill the keys a mirrored scope was written without, from the store it was mirrored from.

    The mirror has written `scope` on every save since the column shipped, but `balance` and
    `start_on_launch` reached the settings model later, so a blob written before then carries
    neither. Reading it as it stands gives both their defaults, and a scanner whose config turned
    balancing off would silently start sampling evenly on its next sweep.

    Only a blob this row's own mirror owns is filled, and only for a key the mirror could not have
    written. A scope somebody set by hand means what it says, including a `balance` deliberately
    left at its default.

    Drops out with the mirror: once every row carries a scope of its own, the blob is the whole
    truth and nothing derives over it.
    """
    missing = [key for key in _MIRROR_PREDATED_SETTINGS if key not in scope]
    if not missing:
        return scope
    derived = derive_scope(source)
    if derived is None:
        return scope
    # Compare with the predated keys taken off both sides: a derivation made today carries them,
    # and a blob the mirror wrote before they existed cannot, so the two only ever agree once
    # they are set aside. What is left is the shape the mirror would have written back then.
    without_predated = {k: v for k, v in derived.items() if k not in _MIRROR_PREDATED_SETTINGS}
    if without_predated != {k: v for k, v in scope.items() if k not in _MIRROR_PREDATED_SETTINGS}:
        # Not this row's own mirror: a scope set by hand, or one whose source store has moved on.
        return scope
    return {**scope, **{key: derived[key] for key in missing if key in derived}}


def scope_for(source: ScopeSource, *, legacy_only: bool = False) -> ExperimentScope | None:
    """The scope this scanner or snapshot watches, or None when it watches every session.

    An unknown or malformed blob reads as None rather than raising: a scanner whose stored scope
    cannot be parsed must still sweep, the way one with no scope does.
    """
    blob = stored_scope(source, legacy_only=legacy_only)
    if blob is None:
        return None
    kind = blob.get("kind")
    if not isinstance(kind, str):
        return None
    scope_cls = SCOPES.get(kind)
    settings_cls = SETTINGS.get(kind)
    if scope_cls is None or settings_cls is None:
        return None
    try:
        settings = settings_cls.model_validate({k: v for k, v in blob.items() if k != "kind"})
    except ValidationError:
        return None
    return scope_cls(settings)


def derive_scope(source: ScopeSource) -> dict[str, Any] | None:
    """The blob to write into the `scope` column for a row that predates it.

    Used by the dual write on save, so a row saved during the migration carries its scope in the new
    column as well as the old store. Returns None when there is nothing to record.
    """
    scope = scope_for(source, legacy_only=True)
    return scope.as_stored() if scope is not None else None


def experiment_id_of(source: ScopeSource) -> int | None:
    """The experiment this scanner watches, from whichever store holds it.

    Read-side redaction and the access checks gate on this, so it has to see every store.
    """
    blob = stored_scope(source)
    if blob is None or blob.get("kind") != ExperimentScope.kind:
        return None
    experiment_id = blob.get("experiment_id")
    return experiment_id if isinstance(experiment_id, int) else None


def settings_of(source: ScopeSource) -> ExperimentScopeSettings | None:
    """The validated settings of an experiment scope, for callers that need `variants`."""
    scope = scope_for(source)
    return scope.settings if scope is not None else None
