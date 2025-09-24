from django.apps import AppConfig
from django.contrib import admin


class ExperimentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.experiments.backend"
    label = "experiments"

    def ready(self):
        # Import and register admin classes when Django is ready

        # TODO: Hacky
        _ = list(admin.site._registry)

        from .admin import ExperimentAdmin, ExperimentSavedMetricAdmin
        from .models import Experiment, ExperimentSavedMetric

        # Register admin classes
        admin.site.register(Experiment, ExperimentAdmin)
        admin.site.register(ExperimentSavedMetric, ExperimentSavedMetricAdmin)
