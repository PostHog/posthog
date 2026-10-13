from collections.abc import Callable
from typing import Any
from uuid import UUID

from products.messaging.backend.facade.contracts import UnlayerNotConfiguredError, UnlayerRenderError
from products.messaging.backend.remote_config import (
    PUSH_APP_ID_CONFIG_KEYS,
    build_push_config as build_push_app_ids,
)
from products.messaging.backend.services import design_operations, design_validation, message_templates
from products.messaging.backend.unlayer import render_design_html as render_unlayer_design

__all__ = [
    "UnlayerNotConfiguredError",
    "UnlayerRenderError",
    "apply_design_operations",
    "build_push_config",
    "find_template_ids_containing",
    "get_template_email_content",
    "is_push_integration_kind",
    "render_design_html",
    "rewrite_template_content",
    "validate_design",
]


def build_push_config(team_id: int) -> dict[str, list[str]]:
    """The `push` key of the SDK remote config: the app ids the team accepts device registrations for."""
    return build_push_app_ids(team_id)


def is_push_integration_kind(kind: str) -> bool:
    return kind in PUSH_APP_ID_CONFIG_KEYS


def apply_design_operations(design: dict, operations: list[dict]) -> dict:
    """Raises a DRF ValidationError keyed on `operations` when an operation does not apply."""
    return design_operations.apply_design_operations(design, operations)


def validate_design(design: dict) -> list[str]:
    return design_validation.validate_design(design)


def render_design_html(design: dict[str, Any]) -> str:
    """Raises UnlayerNotConfiguredError or UnlayerRenderError."""
    return render_unlayer_design(design)


def get_template_email_content(team_id: int, template_id: UUID) -> dict | None:
    return message_templates.get_email_content(team_id, template_id)


def find_template_ids_containing(text: str, *, team_ids: list[int] | None, template_id: str | None) -> list[UUID]:
    return message_templates.find_ids_containing(text, team_ids=team_ids, template_id=template_id)


def rewrite_template_content(
    template_id: UUID, rewrite: Callable[[Any], tuple[Any, int]], *, team_ids: list[int] | None, dry_run: bool
) -> int:
    """Apply `rewrite` to a template's content under a row lock. Returns the number of occurrences it replaced."""
    return message_templates.rewrite_content(template_id, rewrite, team_ids=team_ids, dry_run=dry_run)
