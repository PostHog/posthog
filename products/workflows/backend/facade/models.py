"""
Model-class wiring for workflows.

Re-exports the ``HogFlow`` model class for ``HogFlowViewSet`` under the watched-models allowance
(MODEL_CROSSINGS). The viewset reads and writes workflows through facade functions, but the log,
metrics and access-control mixins it inherits still read the workflow row through ``get_object()``,
and ``UserAccessControl`` resolves the resource from the model instance. Presentation may reach
internals only through the facade. The whole model surface (``backend/models/`` and
``backend/migrations/``) stays in the contract-check inputs, so a change to this class still runs
the full suite.
"""

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

__all__ = ["HogFlow"]
