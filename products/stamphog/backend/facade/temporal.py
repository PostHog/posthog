"""Facade re-export for the stamphog Temporal surface.

The worker registers ``WORKFLOWS``/``ACTIVITIES`` for the stamphog task queue. Isolated
from ``facade/api.py`` so ``temporalio`` never lands on the light data-surface import path.
"""

from products.stamphog.backend.temporal.registry import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
