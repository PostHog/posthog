from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self) -> None:
        # Registers activity signal receivers after the app registry is ready.
        import products.experiments.backend.activity_logging  # noqa: F401, PLC0415
        from products.ai_observability.backend.facade.evaluation_signals import (  # noqa: PLC0415
            connect_evaluation_output_changed,
        )

        connect_evaluation_output_changed(
            _rebuild_eval_pass_rate_metrics, dispatch_uid="experiments_rebuild_eval_pass_rate_metrics"
        )


def _rebuild_eval_pass_rate_metrics(sender: object, *, team_id: int, **kwargs: object) -> None:
    # Imported on first use: the templates module pulls posthog.schema, which must stay off django.setup().
    from products.experiments.backend.llm_metric_templates import rebuild_eval_pass_rate_metrics  # noqa: PLC0415

    rebuild_eval_pass_rate_metrics(team_id)
