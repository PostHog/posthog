from django.apps import AppConfig


class NotebooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.notebooks.backend"
    label = "notebooks"

    def ready(self) -> None:
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

        def _post_trash_change(context, notebook):
            from products.notebooks.backend.app_delivery import revoke_published_app_access

            user = context.user
            was_impersonated = is_impersonated(context.request)
            revoke_published_app_access(
                notebook.team_id, notebook.pk, user if isinstance(user, User) else None, was_impersonated
            )
            organization = context.organization
            if not organization:
                return
            team = context.team
            team_id = getattr(team, "id", None) if team is not None else None
            if not isinstance(team_id, int):
                return
            if not isinstance(user, User):
                return
            log_notebook_activity(
                activity="deleted" if notebook.deleted else "restored",
                notebook=notebook,
                organization_id=organization.id,
                team_id=team_id,
                user=user,
                was_impersonated=was_impersonated,
                changes=(
                    None
                    if notebook.deleted
                    else [Change(type="Notebook", action="changed", field="deleted", before=True, after=False)]
                ),
            )

        register_post_delete_hook("notebook", _post_trash_change)
        register_post_restore_hook("notebook", _post_trash_change)
