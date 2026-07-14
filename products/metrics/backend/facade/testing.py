"""Test-support facade for metrics.

Other products' tests (e.g. alerts) plant metric fixtures through this module so
they never import metrics internals; the seeder writes rows shaped like real
ingest output directly into ClickHouse.
"""

from products.metrics.backend.tests._seeder import seed_metric

__all__ = ["seed_metric"]
