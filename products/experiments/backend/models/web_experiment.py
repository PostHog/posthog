from posthog.models.utils import RootTeamMixin

from products.experiments.backend.models.experiment import Experiment, ExperimentManager, ExperimentQuerySet


class WebExperimentManager(ExperimentManager["WebExperiment"]):
    def get_queryset(self) -> ExperimentQuerySet["WebExperiment"]:
        return super().get_queryset().filter(type="web")


class WebExperiment(Experiment, RootTeamMixin):
    objects = WebExperimentManager()  # type: ignore

    class Meta:
        proxy = True
