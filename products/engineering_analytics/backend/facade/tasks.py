"""Celery wiring facade: the tasks and schedules core registers for this product.

Kept separate from ``api.py`` so beat registration does not import the read layer.
"""

from products.engineering_analytics.backend.tasks.schedules import TEST_CENSUS_CRONTAB
from products.engineering_analytics.backend.tasks.tasks import emit_test_ownership_census

__all__ = [
    "TEST_CENSUS_CRONTAB",
    "emit_test_ownership_census",
]
