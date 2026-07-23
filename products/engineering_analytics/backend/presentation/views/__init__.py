"""DRF views for engineering_analytics.

Named, typed read endpoints over the curated PR/CI query builders, one module per surface area,
composed here into the single ``EngineeringAnalyticsViewSet`` (one URL space, one OpenAPI tag).
Shared parameters, query-param helpers, and error degradation live in ``_base``.
"""

from drf_spectacular.utils import extend_schema

from products.engineering_analytics.backend.presentation.views._base import (
    ENGINEERING_ANALYTICS_TAG,
    EngineeringAnalyticsViewSetBase,
)
from products.engineering_analytics.backend.presentation.views.ci_signals import CISignalsConfigMixin
from products.engineering_analytics.backend.presentation.views.pull_requests import PullRequestActionsMixin
from products.engineering_analytics.backend.presentation.views.sources import SourcesMixin
from products.engineering_analytics.backend.presentation.views.suite_health import SuiteHealthActionsMixin
from products.engineering_analytics.backend.presentation.views.teams import TeamActionsMixin
from products.engineering_analytics.backend.presentation.views.workflows import WorkflowActionsMixin


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(
    SourcesMixin,
    CISignalsConfigMixin,
    PullRequestActionsMixin,
    WorkflowActionsMixin,
    SuiteHealthActionsMixin,
    TeamActionsMixin,
    EngineeringAnalyticsViewSetBase,
):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    # Personal API keys get 403 on any action not enrolled here. Each mixin declares its own
    # actions; TestScopeEnrollment asserts the composition stays in lockstep with the @actions.
    scope_object_read_actions = [
        *SourcesMixin.READ_ACTIONS,
        *CISignalsConfigMixin.READ_ACTIONS,
        *PullRequestActionsMixin.READ_ACTIONS,
        *WorkflowActionsMixin.READ_ACTIONS,
        *SuiteHealthActionsMixin.READ_ACTIONS,
        *TeamActionsMixin.READ_ACTIONS,
    ]
    scope_object_write_actions: list[str] = [
        *CISignalsConfigMixin.WRITE_ACTIONS,
        *SuiteHealthActionsMixin.WRITE_ACTIONS,
    ]
