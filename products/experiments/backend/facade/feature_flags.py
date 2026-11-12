"""Experiment reads for feature flags, which mark each flag that an experiment uses."""

from collections.abc import Collection

from products.experiments.backend.models.experiment import live_experiment_flag_ids


def flag_ids_with_live_experiment(feature_flag_ids: Collection[int], *, using: str) -> frozenset[int]:
    """The ids among `feature_flag_ids` that a non-deleted experiment uses. This is the batch form of
    `api.flag_has_live_experiment`. Flag ids are unique across teams, so pass ids from a team-scoped read.

    Reads from the database alias `using`. Pass the alias that the flags were read from, so that both reads see the
    same database. An empty collection returns an empty set without a query."""
    return live_experiment_flag_ids(feature_flag_ids, using=using)
