"""Lightweight facade re-export of the repo-selection result type.

Kept separate from ``facade.repo_selection`` so callers that only need the framework-free
``RepoSelectionResult`` model don't pull in the repo-selection agent/sandbox/LLM runtime that
``select_repository`` drags in. This matters for modules on the ``django.setup()`` import path
(e.g. signals' ``artefact_schemas``), which must stay dependency-light.
"""

from products.tasks.backend.logic.repo_selection.types import RepoSelectionResult

__all__ = ["RepoSelectionResult"]
