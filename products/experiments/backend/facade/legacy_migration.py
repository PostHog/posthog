"""Legacy migration capability for callers outside the experiments internals."""

from products.experiments.backend import legacy_migration
from products.experiments.backend.facade.contracts import LegacyMigrationError
from products.experiments.backend.legacy_migration import ExperimentMigration

__all__ = [
    "migrate_experiment",
]


def migrate_experiment(
    experiment_id: int, team_id: int, *, migrate_shared_metrics: bool = False
) -> ExperimentMigration:
    """Create a new-engine copy of a legacy experiment, or return the copy made earlier.

    Raises LegacyMigrationError from facade/contracts.py, with the internal error's message, when the experiment
    can't move. See `legacy_migration.migrate_experiment`.
    """
    try:
        return legacy_migration.migrate_experiment(
            experiment_id, team_id, migrate_shared_metrics=migrate_shared_metrics
        )
    except legacy_migration.LegacyMigrationError as error:
        raise LegacyMigrationError(str(error)) from error
