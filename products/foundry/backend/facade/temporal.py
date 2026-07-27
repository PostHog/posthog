"""
Wiring that core registers and dispatches on, as objects: the worker registers
``WORKFLOWS``/``ACTIVITIES`` for the foundry task queue. Isolated from ``facade/api.py`` so
``temporalio`` never lands on the light data-surface import path.
"""

from products.foundry.backend.temporal.registry import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
