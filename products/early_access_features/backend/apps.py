from django.apps import AppConfig


class EarlyAccessFeaturesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.early_access_features.backend"
    label = "early_access_features"

    def ready(self) -> None:
        from posthog.api.file_system.deletion import (
            register_file_system_type,
            register_post_delete_hook,
            register_pre_delete_hook,
        )
        from posthog.models.activity_logging.activity_log import Detail, log_activity
        from posthog.models.activity_logging.model_activity import is_impersonated_session

        def _with_feature_flag(queryset):
            return queryset.select_related("feature_flag")

        register_file_system_type(
            "early_access_feature",
            "early_access_features",
            "EarlyAccessFeature",
            queryset_modifier=_with_feature_flag,
            hard_delete=True,
            allow_restore=False,
            undo_message="Recreate the early access feature and reapply any filters.",
        )

        def _pre_delete(context, feature):
            feature_flag = getattr(feature, "feature_flag", None)
            if feature_flag:
                filters = dict(feature_flag.filters or {})
                filters["super_groups"] = None
                feature_flag.filters = filters
                feature_flag.save(update_fields=["filters"])

        def _post_delete(context, feature):
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
                scope="EarlyAccessFeature",
                activity="deleted",
                detail=Detail(name=getattr(feature, "name", None) or "Untitled feature"),
            )

        register_pre_delete_hook("early_access_feature", _pre_delete)
        register_post_delete_hook("early_access_feature", _post_delete)
