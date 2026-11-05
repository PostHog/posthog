from collections.abc import Callable
from enum import StrEnum

from posthog.dataclasses import frozen

from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration


class DmSetupStepKey(StrEnum):
    # pinned: analytics property values, renaming breaks dashboards
    LINK_ACCOUNT = "link_account"


@frozen
class DmSetupContext:
    integration: WorkspaceIntegration
    slack_user_id: str


@frozen
class DmSetupStep:
    """One step of the setup card. A step that does not apply is left out, and a done step shrinks
    to ``done_text``. Each check reads the database again, so the card stores no step progress."""

    key: DmSetupStepKey
    done_text: str
    applies: Callable[[DmSetupContext], bool]
    is_done: Callable[[DmSetupContext], bool]
    render: Callable[[DmSetupContext], list[dict]]
