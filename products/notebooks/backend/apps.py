from django.apps import AppConfig


class NotebooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.notebooks.backend"
    label = "notebooks"

    def ready(self) -> None:
        from django.db.models.signals import pre_delete

        from posthog.api.file_system.deletion import (
            register_file_system_type,
            register_post_delete_hook,
            register_post_restore_hook,
        )
        from posthog.helpers.impersonation import is_impersonated
        from posthog.models.activity_logging.activity_log import Change
        from posthog.models.user import User

        # Lives in its own module: the API module's imports reach the kernel runtime and the
        # tasks sandbox (modal SDK), which must stay off the django.setup() path.
        from products.notebooks.backend.activity_logging import log_notebook_activity

        register_file_system_type(
            "notebook",
            "notebooks",
            "Notebook",
            lookup_field="short_id",
            undo_message="Send PATCH /api/projects/@current/notebooks/{id} with deleted=false.",
        )

        def _post_delete(context, notebook):
            from products.notebooks.backend.genui import (  # noqa: PLC0415 because Canvas and Tasks stay off startup
                cleanup_removed_genui_nodes,
            )

            cleanup_removed_genui_nodes(notebook)
            organization = context.organization
            if not organization:
                return
            team = context.team
            team_id = getattr(team, "id", None) if team is not None else None
            if not isinstance(team_id, int):
                return
            user = context.user
            if not isinstance(user, User):
                return
            log_notebook_activity(
                activity="deleted",
                notebook=notebook,
                organization_id=organization.id,
                team_id=team_id,
                user=user,
                was_impersonated=is_impersonated(context.request),
            )

        def _post_restore(context, notebook):
            organization = context.organization
            if not organization:
                return
            team = context.team
            team_id = getattr(team, "id", None) if team is not None else None
            if not isinstance(team_id, int):
                return
            user = context.user
            if not isinstance(user, User):
                return
            log_notebook_activity(
                activity="restored",
                notebook=notebook,
                organization_id=organization.id,
                team_id=team_id,
                user=user,
                was_impersonated=is_impersonated(context.request),
                changes=[Change(type="Notebook", action="changed", field="deleted", before=True, after=False)],
            )

        def _pre_hard_delete(*, instance, **kwargs):
            from products.notebooks.backend.genui import (  # noqa: PLC0415 because Canvas and Tasks stay off startup
                cleanup_removed_genui_nodes,
            )

            cleanup_removed_genui_nodes(instance, delete_all=True)

        register_post_delete_hook("notebook", _post_delete)
        register_post_restore_hook("notebook", _post_restore)
        pre_delete.connect(
            _pre_hard_delete,
            sender="notebooks.Notebook",
            dispatch_uid="notebooks_cleanup_genui_before_hard_delete",
            weak=False,
        )
