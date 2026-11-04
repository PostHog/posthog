from typing import TYPE_CHECKING

from django.apps import AppConfig

if TYPE_CHECKING:
    from posthog.api.file_system.deletion import DeletionContext, RestoreContext

    from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
    from products.workflows.backend.services.template_file_guard import LinkedTemplate


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            register_file_system_type,
            register_post_delete_hook,
            register_pre_delete_hook,
            register_pre_restore_hook,
        )
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.workflows.backend import receivers  # noqa: F401, PLC0415 — registers signal receivers
        from products.workflows.backend.models.hog_flow.hog_flow import HogFlow  # noqa: PLC0415

        def log_deletion(context: "DeletionContext", instance: "HogFlow") -> None:
            from products.workflows.backend.services.hog_flow_activity import (  # noqa: PLC0415 — keeps activity dependencies off startup
                log_file_system_workflow_deletion,
            )

            log_file_system_workflow_deletion(context, instance)

        def report_deletion(context: "DeletionContext", instance: "HogFlow") -> None:
            from products.workflows.backend.services.hog_flow_activity import (  # noqa: PLC0415 — keeps activity dependencies off startup
                report_file_system_workflow_deletion,
            )

            report_file_system_workflow_deletion(context, instance)

        register_mixin_model("hog_flow", HogFlow)

        register_file_system_type("hog_flow", "workflows", "HogFlow", soft_delete_field=None)
        register_pre_delete_hook("hog_flow", log_deletion)
        register_post_delete_hook("hog_flow", report_deletion)

        def require_linked_workflow_editor(
            context: "DeletionContext | RestoreContext", template: "LinkedTemplate"
        ) -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                require_linked_workflow_editor,
            )

            require_linked_workflow_editor(context, template)

        # A transactional email template sends through a workflow, so this product guards its project file.
        register_pre_delete_hook("message_template", require_linked_workflow_editor)
        register_pre_restore_hook("message_template", require_linked_workflow_editor)
