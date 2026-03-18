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
        from posthog.models.activity_logging.activity_log import Change
        from posthog.models.activity_logging.model_activity import is_impersonated_session
        from posthog.models.user import User

        from products.notebooks.backend.api.notebook import log_notebook_activity

        register_file_system_type(
            "notebook",
            "notebooks",
            "Notebook",
            lookup_field="short_id",
            undo_message="Send PATCH /api/projects/@current/notebooks/{id} with deleted=false.",
        )

        def _post_delete(context, notebook):
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
                was_impersonated=is_impersonated_session(context.request) if context.request else False,
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
                was_impersonated=is_impersonated_session(context.request) if context.request else False,
                changes=[Change(type="Notebook", action="changed", field="deleted", before=True, after=False)],
            )

        register_post_delete_hook("notebook", _post_delete)
        register_post_restore_hook("notebook", _post_restore)
