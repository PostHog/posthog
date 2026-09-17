from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.cache import SessionStore
from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.experiments.backend.admin.experiment_admin import ExperimentAdmin
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.model_admin = ExperimentAdmin(Experiment, AdminSite())
        now = timezone.now()
        self.draft = self._create_experiment(self.team, "draft")
        self.running = self._create_experiment(self.team, "running", start_date=now)
        self.stopped = self._create_experiment(self.team, "stopped", start_date=now, end_date=now)
        other_organization = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_organization, name="other")
        self.other_org_experiment = self._create_experiment(other_team, "elsewhere")

    def _create_experiment(self, team: Team, name: str, **fields: object) -> Experiment:
        flag = FeatureFlag.objects.create(team=team, created_by=self.user, key=f"{name}-flag", name=name)
        return Experiment.objects.create(team=team, name=name, created_by=self.user, feature_flag=flag, **fields)

    def _changelist_ids(self, params: dict[str, str]) -> set[int]:
        request = RequestFactory().get("/admin/experiments/experiment/", params)
        request.user = self.user
        changelist = self.model_admin.get_changelist_instance(request)
        return set(changelist.get_queryset(request).values_list("id", flat=True))

    @parameterized.expand(
        [
            ("draft", "draft", {"draft", "other_org_experiment"}),
            ("running", "running", {"running"}),
            ("stopped", "stopped", {"stopped"}),
        ]
    )
    def test_status_filter_uses_dates_not_stored_status(self, _name: str, status: str, expected: set[str]) -> None:
        Experiment.objects.update(status=None)
        expected_ids = {getattr(self, attr).id for attr in expected}
        assert self._changelist_ids({"status": status}) == expected_ids

    def test_organization_filter_scopes_to_one_organization(self) -> None:
        assert self._changelist_ids({"organization": str(self.organization.id)}) == {
            self.draft.id,
            self.running.id,
            self.stopped.id,
        }

    def test_organization_filter_ignores_a_value_that_is_not_a_uuid(self) -> None:
        all_ids = {self.draft.id, self.running.id, self.stopped.id, self.other_org_experiment.id}
        assert self._changelist_ids({"organization": "invalid"}) == all_ids

    @parameterized.expand([("post_starts_manual_run", "post", True), ("get_is_a_noop", "get", False)])
    @patch("products.experiments.backend.admin.recalculation_panel.start_metrics_recalculation_workflow")
    def test_start_recalculation_view(self, _name: str, method: str, expects_run: bool, mock_start: MagicMock) -> None:
        request = getattr(RequestFactory(), method)("/")
        request.user = self.user
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        with patch.object(self.model_admin, "has_change_permission", return_value=True):
            response = self.model_admin.start_recalculation_view(request, str(self.running.pk))

        run = ExperimentMetricsRecalculation.objects.unscoped().filter(experiment=self.running).first()
        assert (run is not None) is expects_run
        assert mock_start.called is expects_run
        if run is not None:
            assert run.trigger == ExperimentMetricsRecalculation.Trigger.MANUAL
            assert str(run.pk) in response.url
