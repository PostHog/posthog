from django.apps import AppConfig


class SurveysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.surveys.backend"
    label = "surveys"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (
            register_file_system_type,
            register_post_delete_hook,
            register_pre_delete_hook,
        )
        from posthog.models.activity_logging.activity_log import Detail, log_activity
        from posthog.models.activity_logging.model_activity import is_impersonated_session

        def _with_flags(queryset):
            return queryset.select_related("targeting_flag", "internal_targeting_flag")

        register_file_system_type(
            "survey",
            "posthog",
            "Survey",
            queryset_modifier=_with_flags,
            hard_delete=True,
            allow_restore=False,
            undo_message="Create a new survey using the saved configuration.",
        )

        def _pre_delete(context, survey):
            for attr in ("targeting_flag", "internal_targeting_flag"):
                flag = getattr(survey, attr, None)
                if flag:
                    flag.delete()

        def _post_delete(context, survey):
            organization = context.organization
            if not organization:
                return
            ref = context.entry.ref
            if not ref:
                return
            log_activity(
                organization_id=organization.id,
                team_id=getattr(context.team, "id", None),
                user=context.user,
                was_impersonated=is_impersonated_session(context.request) if context.request else False,
                item_id=str(ref),
                scope="Survey",
                activity="deleted",
                detail=Detail(name=getattr(survey, "name", None)),
            )

        register_pre_delete_hook("survey", _pre_delete)
        register_post_delete_hook("survey", _post_delete)
