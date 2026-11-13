from typing import TYPE_CHECKING, Any

from django.apps import AppConfig

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from posthog.api.file_system.deletion import DeletionContext, FileChangeContext, RestoreContext

    from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
    from products.workflows.backend.services.template_file_guard import LinkedTemplate


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.workflows.backend"
    label = "workflows"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            register_delete_lock,
            register_file_change_check,
            register_file_system_type,
            register_post_delete_hook,
            register_pre_delete_hook,
            register_pre_restore_hook,
            register_prepare_delete_hook,
        )
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.actions.backend.facade.api import on_action_saved  # noqa: PLC0415
        from products.workflows.backend import receivers  # noqa: F401, PLC0415 — registers signal receivers
        from products.workflows.backend.models.hog_flow.hog_flow import (  # noqa: PLC0415
            HogFlow,
            action_saved_for_hog_flows,
        )

        # Compiled filters embed each action's matcher, so they must be rebuilt when an action is saved.
        on_action_saved(action_saved_for_hog_flows, dispatch_uid="workflows.hog_flows.action_saved")

        def refuse_unarchived_then_log_deletion(context: "DeletionContext", instance: "HogFlow") -> None:
            from products.workflows.backend.services.hog_flow_activity import (  # noqa: PLC0415 — keeps activity dependencies off startup
                log_file_system_workflow_deletion,
                require_archived_before_delete,
            )

            require_archived_before_delete(instance)
            log_file_system_workflow_deletion(context, instance)

        def report_deletion(context: "DeletionContext", instance: "HogFlow") -> None:
            from products.workflows.backend.services.hog_flow_activity import (  # noqa: PLC0415 — keeps activity dependencies off startup
                report_file_system_workflow_deletion,
            )

            report_file_system_workflow_deletion(context, instance)

        register_mixin_model("hog_flow", HogFlow)

        register_file_system_type("hog_flow", "workflows", "HogFlow", soft_delete_field=None)
        register_pre_delete_hook("hog_flow", refuse_unarchived_then_log_deletion)
        register_post_delete_hook("hog_flow", report_deletion)

        def require_linked_workflow_editor(
            context: "DeletionContext | RestoreContext | FileChangeContext", template: "LinkedTemplate"
        ) -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                require_linked_workflow_editor,
            )

            require_linked_workflow_editor(context, template)

        def lock_templates_for_delete(templates: "QuerySet[Any]") -> "list[Model]":
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                lock_templates_for_delete,
            )

            return lock_templates_for_delete(templates)

        def prepare_linked_workflows(request: Any | None, team_id: int, templates: "QuerySet[Any]") -> None:
            from products.workflows.backend.services.template_file_guard import (  # noqa: PLC0415 — keeps access control dependencies off startup
                prepare_linked_workflows,
            )

            prepare_linked_workflows(request, team_id, templates)

        register_prepare_delete_hook("message_template", prepare_linked_workflows)
        register_delete_lock(
            "message_template",
            lock_templates_for_delete,
            fields=(
                "id",
                "team_id",
                "transactional_hog_flow_id",
                "deleted",
                "name",
                "created_at",
                "created_by_id",
                "updated_at",
            ),
        )
        register_pre_delete_hook("message_template", require_linked_workflow_editor)
        register_pre_restore_hook("message_template", require_linked_workflow_editor)
        register_file_change_check(
            "message_template", require_linked_workflow_editor, fields=("id", "team_id", "transactional_hog_flow_id")
        )
