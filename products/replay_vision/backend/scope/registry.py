"""Maps a stored `scope.kind` to its implementation. One entry per kind the product supports."""

from products.replay_vision.backend.scope.experiment import ExperimentScope, ExperimentScopeSettings

SCOPES: dict[str, type[ExperimentScope]] = {ExperimentScope.kind: ExperimentScope}

SETTINGS: dict[str, type[ExperimentScopeSettings]] = {ExperimentScope.kind: ExperimentScopeSettings}
