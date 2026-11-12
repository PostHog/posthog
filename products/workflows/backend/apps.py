from typing import TYPE_CHECKING, Any, cast

from django.apps import AppConfig

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from posthog.api.file_system.deletion import DeletionContext, FileChangeContext, RestoreContext

    from products.workflows.backend.services.template_file_guard import LinkedTemplate


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            register_file_change_check,
            register_pre_delete_hook,
            register_pre_restore_hook,
            register_prepare_delete_hook,
        )

        from products.actions.backend.facade.api import on_action_saved  # noqa: PLC0415
        from products.workflows.backend import receivers  # noqa: F401, PLC0415 — registers signal receivers
        from products.workflows.backend.models.hog_flow.hog_flow import action_saved_for_hog_flows  # noqa: PLC0415

        # Compiled filters embed each action's matcher, so they must be rebuilt when an action is saved.
        on_action_saved(action_saved_for_hog_flows, dispatch_uid="workflows.hog_flows.action_saved")

        def require_linked_workflow_editor(
            context: "DeletionContext | RestoreContext | FileChangeContext", template: "LinkedTemplate"
        ) -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                require_linked_workflow_editor,
            )

            require_linked_workflow_editor(context, template)

        def lock_then_require_linked_workflow_editor(context: "DeletionContext", template: "LinkedTemplate") -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                lock_template_for_delete,
            )

            lock_template_for_delete(cast("Model", template))
            require_linked_workflow_editor(context, template)

        def prepare_linked_workflows(request: Any | None, team_id: int, templates: "QuerySet[Any]") -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                prepare_linked_workflows,
            )

            prepare_linked_workflows(request, team_id, templates)

        register_prepare_delete_hook("message_template", prepare_linked_workflows)
        register_pre_delete_hook("message_template", lock_then_require_linked_workflow_editor)
        register_pre_restore_hook("message_template", require_linked_workflow_editor)
        register_file_change_check(
            "message_template", require_linked_workflow_editor, fields=("id", "team_id", "transactional_hog_flow_id")
        )
