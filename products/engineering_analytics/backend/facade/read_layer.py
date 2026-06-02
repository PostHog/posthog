"""Facade entry point for the curated read layer.

Re-exports the view builder that core's ``Database.create_for`` calls to register
this product's per-team HogQL views. Kept separate from ``api.py`` so the core
import path pulls in only the view-construction code (HogQL models + warehouse
table lookup), not the runtime query layer — importing ``api.py`` would reach
``posthog.hogql.query``, which imports ``Database``, forming a cycle.
"""

from products.engineering_analytics.backend.logic.views.orchestrator import build_all_engineering_analytics_views

__all__ = ["build_all_engineering_analytics_views"]
