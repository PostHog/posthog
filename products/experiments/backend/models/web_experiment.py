from posthog.models.utils import RootTeamManager, RootTeamMixin

from products.experiments.backend.models.experiment import Experiment


class WebExperimentManager(RootTeamManager):
    def get_queryset(self):
        return super().get_queryset().filter(type="web")


class WebExperiment(Experiment, RootTeamMixin):
    objects = WebExperimentManager()  # type: ignore

    class Meta:
        proxy = True
