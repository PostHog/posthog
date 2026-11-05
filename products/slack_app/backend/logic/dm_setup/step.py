from collections.abc import Callable
from enum import StrEnum

from posthog.dataclasses import frozen

from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration


class DmSetupStepKey(StrEnum):
    # pinned: analytics property values and stored skip keys, renaming breaks both
    LINK_ACCOUNT = "link_account"
    MODEL = "model"
    REPLIES_IN_THREADS = "replies_in_threads"


@frozen
class DmSetupContext:
    integration: WorkspaceIntegration
    slack_user_id: str


@frozen
class DmSetupStep:
    """``applies`` and ``is_done`` read the database on every plan, so done status is never stored."""

    key: DmSetupStepKey
    title: str
    done_text: str
    skippable: bool
    applies: Callable[[DmSetupContext], bool]
    is_done: Callable[[DmSetupContext], bool]
    render: Callable[[DmSetupContext], list[dict]]
