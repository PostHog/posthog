from uuid import UUID

from products.messaging.backend.facade.api import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    apply_design_operations,
    get_template_email_content,
    render_design_html,
    validate_design,
)
from products.workflows.backend.facade.contracts import (
    EditedEmailDesign,
    EmailDesignRenderFailed,
    EmailDesignRenderingNotConfigured,
)


def get_email_template_content(team_id: int, template_id: UUID) -> dict | None:
    return get_template_email_content(team_id, template_id)


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
