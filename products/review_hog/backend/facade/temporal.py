"""
Wiring that core registers and dispatches on, as objects: the worker registers
``WORKFLOWS``/``ACTIVITIES``. Isolated from ``facade/api.py`` so ``temporalio`` never lands
on the light data-surface import path.
"""

from products.review_hog.backend.temporal import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
