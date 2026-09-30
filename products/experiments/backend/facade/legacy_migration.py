"""Legacy migration capability, re-exported for callers outside the experiments internals."""

from products.experiments.backend.legacy_migration import LegacyMigrationError, migrate_experiment

__all__ = [
    "LegacyMigrationError",
    "migrate_experiment",
]
