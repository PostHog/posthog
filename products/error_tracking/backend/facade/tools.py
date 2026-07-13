"""Facade re-export for error tracking Max tools.

The AI agent presets (``ee/hogai``) register this tool class with the assistant.
It crosses the boundary as an object, not data, so it lives in its own facade
submodule. ``search_issues`` imports ``ee.hogai`` itself, so consumers must keep
importing this lazily (inside the registration call site) to avoid a circular
import on the ``django.setup()`` path.
"""

from products.error_tracking.backend.logic.tools.search_issues import SearchErrorTrackingIssuesTool

__all__ = ["SearchErrorTrackingIssuesTool"]
