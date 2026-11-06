"""Legacy migration capability for callers outside the experiments internals."""

from products.experiments.backend.legacy_migration import migrate_experiment

__all__ = [
    "migrate_experiment",
]
