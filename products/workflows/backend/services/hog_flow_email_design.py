from uuid import UUID

from products.messaging.backend.api.design_operations import apply_design_operations
from products.messaging.backend.api.design_validation import validate_design
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError, render_design_html
from products.workflows.backend.facade.contracts import (
    EditedEmailDesign,
    EmailDesignRenderFailed,
    EmailDesignRenderingNotConfigured,
)


def get_email_template_content(team_id: int, template_id: UUID) -> dict | None:
    template = MessageTemplate.objects.filter(team_id=team_id, id=template_id, deleted=False).first()
    email_content = (template.content or {}).get("email") if template else None
    return email_content if isinstance(email_content, dict) else None


def apply_email_design_operations(design: dict, operations: list[dict]) -> EditedEmailDesign:
    new_design = apply_design_operations(design, operations)
    return EditedEmailDesign(design=new_design, warnings=tuple(validate_design(new_design)))


def render_email_design_html(design: dict) -> str:
    try:
        return render_design_html(design)
    except UnlayerNotConfiguredError as e:
        raise EmailDesignRenderingNotConfigured() from e
    except UnlayerRenderError as e:
        raise EmailDesignRenderFailed(str(e)) from e
