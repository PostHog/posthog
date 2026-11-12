from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers the activity and change signal receivers after the app registry is ready.
        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            DeletionContext,
            RestoreContext,
            register_file_system_type,
            register_post_delete_hook,
            register_post_restore_hook,
        )
        from posthog.helpers.impersonation import is_impersonated  # noqa: PLC0415
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity  # noqa: PLC0415
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415
        from posthog.models.resource_transfer.registered_models import register_model  # noqa: PLC0415

        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415
        import products.experiments.backend.facade.change_signals  # noqa: F401, PLC0415
        from products.experiments.backend.models.experiment import (  # noqa: PLC0415
            Experiment,
            ExperimentHoldout,
            ExperimentSavedMetric,
            ExperimentToSavedMetric,
        )

        # Core keeps per-model registries for unfiled items and resource transfer. Registering from here
        # keeps those modules from importing this product's models.
        register_mixin_model("experiment", Experiment)
        register_model("Experiment", Experiment)
        register_model("ExperimentHoldout", ExperimentHoldout)
        register_model("ExperimentSavedMetric", ExperimentSavedMetric)
        register_model("ExperimentToSavedMetric", ExperimentToSavedMetric)

        register_file_system_type(
            "experiment",
            "experiments",
            "Experiment",
            undo_message="Send PATCH /api/projects/@current/experiments/{id} with deleted=false.",
        )

        def _log_file_system_activity(
            context: DeletionContext | RestoreContext,
            experiment: Experiment,
            activity: str,
            changes: list[Change] | None = None,
        ) -> None:
            organization = context.organization
            if not organization:
                return
            log_activity(
                organization_id=organization.id,
                team_id=getattr(context.team, "id", None),
                user=context.user,
                was_impersonated=is_impersonated(context.request),
                item_id=str(experiment.id),
                scope="Experiment",
                activity=activity,
                detail=Detail(
                    name=(experiment.name or "").strip() or "Untitled experiment",
                    type="experiment",
                    changes=changes,
                ),
            )

        def _post_delete(context: DeletionContext, experiment: Experiment) -> None:
            _log_file_system_activity(context, experiment, "deleted")

        def _post_restore(context: RestoreContext, experiment: Experiment) -> None:
            _log_file_system_activity(
                context,
                experiment,
                "restored",
                changes=[Change(type="Experiment", action="changed", field="deleted", before=True, after=False)],
            )

        register_post_delete_hook("experiment", _post_delete)
        register_post_restore_hook("experiment", _post_restore)

        from products.experiments.backend import task_profiles  # noqa: PLC0415

        task_profiles.register()
