"""Reads a scanner's scope from whichever store currently holds it.

Three stores answer the same question while the migration runs. This is the one place that order is
written down, so a caller never has to know which store a given row uses.
"""

from typing import Any

from pydantic import ValidationError

from products.replay_vision.backend.scope.base import ScopeSource
from products.replay_vision.backend.scope.experiment import ExperimentScope, ExperimentScopeSettings
from products.replay_vision.backend.scope.registry import SCOPES, SETTINGS


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
        return scope

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
