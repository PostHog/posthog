"""Django app configuration for messaging."""

from typing import TYPE_CHECKING

from django.apps import AppConfig

from rest_framework.exceptions import PermissionDenied

if TYPE_CHECKING:
    from posthog.api.file_system.deletion import DeletionContext, RestoreContext

    from products.messaging.backend.models.message_template import MessageTemplate


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.messaging.backend"
    label = "messaging"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            register_file_system_type,
            register_pre_delete_hook,
            register_pre_restore_hook,
        )
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.messaging.backend.models.message_template import MessageTemplate  # noqa: PLC0415

        def require_linked_workflow_editor(
            context: "DeletionContext | RestoreContext", template: "MessageTemplate"
        ) -> None:
            if template.transactional_hog_flow_id is None:
                return
            if context.user is None:
                raise PermissionDenied("You need editor access to this template's transactional email workflow.")
            from products.access_control.backend.facade.user_access_control import (  # noqa: PLC0415 — keeps view dependencies off startup
                UserAccessControl,
            )
            from products.messaging.backend.presentation.views.message_templates import (  # noqa: PLC0415 — keeps view dependencies off startup
                require_workflow_editor,
            )

            require_workflow_editor(
                template.team_id,
                template.transactional_hog_flow_id,
                UserAccessControl(user=context.user, team=template.team),
            )

        register_mixin_model("message_template", MessageTemplate)
        register_file_system_type("message_template", "messaging", "MessageTemplate")
        register_pre_delete_hook("message_template", require_linked_workflow_editor)
        register_pre_restore_hook("message_template", require_linked_workflow_editor)
