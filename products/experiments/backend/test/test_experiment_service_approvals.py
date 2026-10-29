from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature

from products.approvals.backend.exceptions import ApplyFailed, ApprovalRequired, PreconditionFailed
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import apply_change_request
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestExperimentServiceApprovals(APIBaseTest):
    """launch/pause/resume flip the linked flag's `active` state, which must pass through
    the FeatureFlagSerializer approval gate (action `feature_flag.enable`/`feature_flag.disable`)."""

    _METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def _request(self) -> Any:
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

    def _create_enable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_disable_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.disable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_update_policy(self) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create_draft_experiment(self, feature_flag_key: str) -> Experiment:
        return self._service().create_experiment(
            name="Approval Test",
            feature_flag_key=feature_flag_key,
            metrics=[self._METRIC],
            primary_metrics_ordered_uuids=["m1"],
            allow_unknown_events=True,
        )

    def _create_launched_experiment(self, feature_flag_key: str) -> Experiment:
        experiment = self._create_draft_experiment(feature_flag_key)
        # Launch without a policy in place so the flag is genuinely active afterwards.
        self._service().launch_experiment(experiment, request=self._request())
        experiment.refresh_from_db()
        return experiment

    def test_launch_under_enable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_draft_experiment("launch-gated")
        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().launch_experiment(experiment, request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        assert experiment.start_date is None

    def test_launch_under_enable_policy_without_request_requires_approval(self, _mock_enabled):
        # Internal callers (e.g. _create_running_experiment) invoke launch with request=None,
        # which builds a _ServiceRequest shim. The gate must still raise ApprovalRequired
        # rather than crashing on a missing request attribute.
        experiment = self._create_draft_experiment("launch-gated-no-request")
        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().launch_experiment(experiment)

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False
        assert experiment.start_date is None

    def test_pause_under_disable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_launched_experiment("pause-gated")
        assert experiment.feature_flag.active is True
        self._create_disable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().pause_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is True

    def test_resume_under_enable_policy_requires_approval(self, _mock_enabled):
        experiment = self._create_launched_experiment("resume-gated")
        # Pause it first (no policy yet) so it's genuinely paused.
        self._service().pause_experiment(experiment, request=self._request())
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False

        self._create_enable_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().resume_experiment(experiment, request=self._request())

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is False

    def test_launch_without_policy_flips_flag_and_sets_start_date(self, _mock_enabled):
        experiment = self._create_draft_experiment("launch-ungated")

        launched = self._service().launch_experiment(experiment, request=self._request())

        assert launched.start_date is not None
        launched.feature_flag.refresh_from_db()
        assert launched.feature_flag.active is True

    def test_ship_variant_under_update_policy_requires_approval(self, _mock_enabled):
        # ship_variant rewrites the flag's variant rollout (50/50 -> 100/0), a rollout_percentage
        # change gated by feature_flag.update. It routes through FeatureFlagSerializer, so the gate
        # must fire and leave the flag's filters untouched.
        experiment = self._create_launched_experiment("ship-gated")
        original_filters = experiment.feature_flag.filters
        original_variants = original_filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 50 for v in original_variants)

        self._create_update_policy()

        with self.assertRaises(ApprovalRequired):
            self._service().ship_variant(experiment, variant_key="test", request=self._request())

        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        # Flag distribution unchanged and experiment not ended.
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        assert experiment.end_date is None

    def test_update_experiment_variant_edit_under_update_policy_leaves_pending_cr(self, _mock_enabled):
        # update_experiment() syncs a variant/rollout change back through FeatureFlagSerializer,
        # gated by feature_flag.update. The gated flag write runs OUTSIDE the method's atomic block
        # (like ship_variant/launch/pause/resume), so ApprovalRequired leaves the flag untouched
        # AND the pending ChangeRequest survives for an approver to act on — it is not rolled back.
        experiment = self._create_launched_experiment("update-gated")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]
        self._create_update_policy()

        new_variants = [
            {"key": "control", "rollout_percentage": 10},
            {"key": "test", "rollout_percentage": 90},
        ]
        context = {
            "request": self._request(),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
            "get_organization": lambda: self.organization,
        }

        with self.assertRaises(ApprovalRequired):
            self._service().update_experiment(
                experiment,
                {"update_feature_flag_params": True},
                feature_flag_config={"filters": {"multivariate": {"variants": new_variants}}},
                serializer_context=context,
            )

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants
        assert ChangeRequest.objects.filter(state=ChangeRequestState.PENDING).count() == 1
        assert ChangeRequest.objects.filter(state=ChangeRequestState.APPLIED).count() == 0

    def test_update_experiment_invalid_payload_does_not_commit_flag_variant_change(self, _mock_enabled):
        # A single update that both rewrites the flag's variant rollout (update_feature_flag_params=True)
        # and carries an invalid stats_config must fail closed WITHOUT committing the flag change. The flag
        # write autocommits (no ATOMIC_REQUESTS), so the payload validation has to run before it — otherwise
        # a 400 would leave the flag rewritten while the experiment stays untouched (flag/experiment drift).
        # No policy here: without the pre-flag validation the flag write would succeed and commit.
        experiment = self._create_launched_experiment("update-invalid-payload")
        original_variants = experiment.feature_flag.filters["multivariate"]["variants"]

        new_variants = [
            {"key": "control", "rollout_percentage": 10},
            {"key": "test", "rollout_percentage": 90},
        ]
        context = {
            "request": self._request(),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
            "get_organization": lambda: self.organization,
        }

        with self.assertRaises(ValidationError):
            self._service().update_experiment(
                experiment,
                {
                    "update_feature_flag_params": True,
                    # baseline_variant_key references a variant that does not exist in the resolved set.
                    "stats_config": {"baseline_variant_key": "nonexistent"},
                },
                feature_flag_config={"filters": {"multivariate": {"variants": new_variants}}},
                serializer_context=context,
            )

        experiment.feature_flag.refresh_from_db()
        # The invalid payload must not have committed the flag's variant rewrite.
        assert experiment.feature_flag.filters["multivariate"]["variants"] == original_variants


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestCreatingALiveExperimentUnderALaunchPolicy(APIBaseTest):
    """A create that starts the experiment at once cannot be sent for approval.

    The flag is minted before the experiment row exists, so it is unowned at that instant and
    `experiment.launch` cannot see it. Only the API can reach this: the experiment form sends no
    start date, so everything it creates is a draft.
    """

    _METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _policy(self, action_key: str) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _create(self, key: str, start_date: Any = None) -> Experiment:
        return ExperimentService(team=self.team, user=self.user).create_experiment(
            name="Live create",
            feature_flag_key=key,
            metrics=[self._METRIC],
            primary_metrics_ordered_uuids=["m1"],
            allow_unknown_events=True,
            start_date=start_date,
        )

    def _scoped_by_owner(self, enabled: bool):
        return patch(
            "products.experiments.backend.experiment_service.scope_by_owner_enabled",
            return_value=enabled,
        )

    def test_a_live_create_is_refused(self, _mock_enabled) -> None:
        self._policy("experiment.launch")

        with self._scoped_by_owner(True), self.assertRaises(ValidationError) as caught:
            self._create("live-flag", start_date=datetime(2026, 1, 1, tzinfo=UTC))

        assert "draft" in str(caught.exception)
        assert not Experiment.objects.filter(team=self.team).exists()
        assert not ChangeRequest.objects.filter(team=self.team).exists()

    def test_a_draft_create_is_allowed(self, _mock_enabled) -> None:
        """The route the refusal points at has to work, or the message sends nobody anywhere."""
        self._policy("experiment.launch")

        with self._scoped_by_owner(True):
            experiment = self._create("draft-flag")

        assert experiment.is_draft
        assert experiment.feature_flag is not None
        assert experiment.feature_flag.active is False

    @parameterized.expand(
        [
            ("no_launch_policy", False, True),
            ("approvals_not_available", True, False),
        ]
    )
    def test_a_live_create_is_allowed_when_launching_needs_no_approval(
        self, _mock_enabled, _name: str, launch_policy: bool, approvals_available: bool
    ) -> None:
        if launch_policy:
            self._policy("experiment.launch")
        if not approvals_available:
            self.organization.available_product_features = []
            self.organization.save()

        with self._scoped_by_owner(True):
            experiment = self._create("live-ungated", start_date=datetime(2026, 1, 1, tzinfo=UTC))

        assert not experiment.is_draft
        assert experiment.feature_flag is not None
        assert experiment.feature_flag.active is True

    def test_a_live_create_still_reaches_the_flag_policy_before_rollout(self, _mock_enabled) -> None:
        """Before the organization scopes by flag owner the flag family gates the create.

        The guard must not pre-empt that, or an organization would get a refusal where it used to
        get a change request it could approve.
        """
        self._policy("experiment.launch")
        self._policy("feature_flag.enable")

        with self._scoped_by_owner(False), self.assertRaises(ApprovalRequired):
            self._create("pre-rollout-flag", start_date=datetime(2026, 1, 1, tzinfo=UTC))


@contextmanager
def _stub_exposure_snapshot():
    with (
        patch.object(
            ExperimentService, "_fetch_exposed_person_uuids", return_value=["00000000-0000-0000-0000-000000000001"]
        ),
        patch(
            "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
            new=lambda team_id, uuids, **kwargs: [(index + 1, person_uuid) for index, person_uuid in enumerate(uuids)],
        ),
        patch(
            "products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_id_uuid_pairs_skip_validation",
            return_value=0,
        ),
    ):
        yield


_ROLLOUT_OVER_50 = {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestExperimentOperationsUnderTheUpdatePolicy(APIBaseTest):
    _METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _running_experiment(self, key: str, *, frozen: bool) -> Experiment:
        service = ExperimentService(team=self.team, user=self.user)
        experiment = service.create_experiment(
            name=key,
            feature_flag_key=key,
            metrics=[self._METRIC],
            primary_metrics_ordered_uuids=["m1"],
            allow_unknown_events=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        if frozen:
            request = APIRequestFactory().post("/fake")
            request.user = self.user
            experiment = service.freeze_exposure(experiment, request=request)
        return experiment

    def _policy(self, action_key: str, conditions: dict[str, Any]) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions=conditions,
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _status(self, experiment: Experiment) -> str:
        return Experiment.objects.get(id=experiment.id).status_label

    def _snapshot_count(self) -> int:
        return Cohort.objects.filter(team=self.team, name__startswith="Exposure snapshot", deleted=False).count()

    @parameterized.expand(
        [
            ("freeze", "freeze_exposure", False, "exposure_frozen"),
            ("unfreeze", "unfreeze_exposure", True, "running"),
            ("reset", "reset", False, "draft"),
        ]
    )
    def test_an_unconditioned_update_policy_holds_the_operation_until_approval(
        self, _mock_enabled, name: str, endpoint: str, frozen: bool, status_after: str
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"{name}-held", frozen=frozen)
            status_before = self._status(experiment)
            snapshots_before = self._snapshot_count()
            self._policy("experiment.update", conditions={})

            with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=True):
                response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment.id}/{endpoint}/")

                assert response.status_code == 409, response.json()
                change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
                assert change_request.action_key == f"experiment.{endpoint}"
                assert change_request.resource_id == str(experiment.id)
                assert self._status(experiment) == status_before
                # Nothing the operation creates exists before approval, the freeze snapshot included.
                assert self._snapshot_count() == snapshots_before

                apply_change_request(change_request)

            assert self._status(experiment) == status_after

    @parameterized.expand(
        [
            (f"{name}_{case}", endpoint, frozen, status_after, conditions, rolled_out)
            for name, endpoint, frozen, status_after in [
                ("freeze", "freeze_exposure", False, "exposure_frozen"),
                ("unfreeze", "unfreeze_exposure", True, "running"),
                ("reset", "reset", False, "draft"),
            ]
            for case, conditions, rolled_out in [
                ("under_a_rollout_condition", _ROLLOUT_OVER_50, True),
                ("before_rollout", {}, False),
            ]
        ]
    )
    def test_the_operation_runs_at_once_when_the_update_policy_does_not_cover_it(
        self,
        _mock_enabled,
        _name: str,
        endpoint: str,
        frozen: bool,
        status_after: str,
        conditions: dict[str, Any],
        rolled_out: bool,
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"{endpoint}-open", frozen=frozen)
            self._policy("experiment.update", conditions=conditions)
            self._policy("feature_flag.update", conditions={})

            with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=rolled_out):
                response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment.id}/{endpoint}/")

        assert response.status_code == 200, response.json()
        assert self._status(experiment) == status_after
        assert not ChangeRequest.objects.filter(team=self.team).exists()

    def _held_operation(self, experiment: Experiment, endpoint: str) -> ChangeRequest:
        self._policy("experiment.update", conditions={})
        with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=True):
            response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment.id}/{endpoint}/")
        assert response.status_code == 409, response.json()
        return ChangeRequest.objects.get(id=response.json()["change_request_id"])

    @parameterized.expand(
        [
            ("held_then_applied", True, False, {}),
            ("held_with_a_rename_then_applied", True, True, {"name": "renamed"}),
            ("before_rollout", False, True, {"name": "renamed"}),
        ]
    )
    def test_clearing_the_start_date_changes_only_what_the_update_names(
        self, _mock_enabled, name: str, rolled_out: bool, frozen: bool, other_fields: dict[str, Any]
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"clear-start-{name}", frozen=frozen)
            self._policy("experiment.update", conditions={})

            with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=rolled_out):
                response = self.client.patch(
                    f"/api/projects/{self.team.id}/experiments/{experiment.id}/",
                    {"start_date": None, **other_fields},
                    format="json",
                )
                if rolled_out:
                    assert response.status_code == 409, response.json()
                    change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
                    assert change_request.action_key == "experiment.reset"
                    assert Experiment.objects.get(id=experiment.id).start_date is not None
                    apply_change_request(change_request)
                else:
                    assert response.status_code == 200, response.json()

        experiment = Experiment.objects.get(id=experiment.id)
        assert experiment.start_date is None
        assert experiment.name == other_fields.get("name", f"clear-start-{name}")
        assert experiment.flag_carries_exposure_freeze is frozen

    @parameterized.expand(
        [
            ("freeze_after_a_relaunch", "freeze_exposure", False, "start_date"),
            ("unfreeze_after_a_relaunch", "unfreeze_exposure", True, "start_date"),
            ("reset_after_a_relaunch", "reset", False, "start_date"),
            ("reset_after_the_end", "reset", False, "end_date"),
        ]
    )
    def test_a_request_from_an_earlier_run_neither_applies_nor_blocks_a_new_one(
        self, _mock_enabled, _name: str, endpoint: str, frozen: bool, changed_date: str
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"earlier-run-{_name}", frozen=frozen)
            change_request = self._held_operation(experiment, endpoint)
            Experiment.objects.filter(id=experiment.id).update(**{changed_date: datetime(2026, 2, 1, tzinfo=UTC)})
            status_before = self._status(experiment)

            with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=True):
                response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment.id}/{endpoint}/")
            assert response.status_code == 409, response.json()
            assert response.json()["change_request_id"] != str(change_request.id)

            with self.assertRaises(PreconditionFailed):
                apply_change_request(change_request)

        change_request.refresh_from_db()
        assert change_request.state == ChangeRequestState.FAILED
        assert self._status(experiment) == status_before

    @parameterized.expand(
        [
            ("freeze", "freeze_exposure", False),
            ("unfreeze", "unfreeze_exposure", True),
            ("reset", "reset", False),
        ]
    )
    def test_a_request_for_a_deleted_experiment_does_not_apply(
        self, _mock_enabled, _name: str, endpoint: str, frozen: bool
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"deleted-{endpoint}", frozen=frozen)
            change_request = self._held_operation(experiment, endpoint)
            Experiment.objects.filter(id=experiment.id).update(deleted=True)

            with self.assertRaises(PreconditionFailed):
                apply_change_request(change_request)

        change_request.refresh_from_db()
        assert change_request.state == ChangeRequestState.FAILED
        assert Experiment.objects.get(id=experiment.id).flag_carries_exposure_freeze is frozen

    @parameterized.expand(
        [
            ("unfreeze_while_paused", "unfreeze_exposure", True, "paused"),
            ("unfreeze_after_an_unstamped_group", "unfreeze_exposure", True, "unstamped_group"),
            ("freeze_after_a_direct_freeze", "freeze_exposure", False, "direct_freeze"),
        ]
    )
    def test_an_operation_the_experiment_moved_past_fails_instead_of_counting_as_applied(
        self, _mock_enabled, _name: str, endpoint: str, frozen: bool, change: str
    ) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment(f"moved-past-{_name}", frozen=frozen)
            change_request = self._held_operation(experiment, endpoint)
            flag = FeatureFlag.objects.get(id=experiment.feature_flag_id)
            if change == "paused":
                FeatureFlag.objects.filter(id=flag.id).update(active=False)
            elif change == "unstamped_group":
                groups = [*flag.filters["groups"], {"properties": [], "rollout_percentage": 5}]
                FeatureFlag.objects.filter(id=flag.id).update(filters={**flag.filters, "groups": groups})
            else:
                request = APIRequestFactory().post("/fake")
                request.user = self.user
                ExperimentService(team=self.team, user=self.user).freeze_exposure(experiment, request=request)
            filters_before = FeatureFlag.objects.get(id=flag.id).filters

            with self.assertRaises(PreconditionFailed):
                apply_change_request(change_request)

        change_request.refresh_from_db()
        assert change_request.state == ChangeRequestState.FAILED
        assert FeatureFlag.objects.get(id=flag.id).filters == filters_before

    @parameterized.expand([("missing",), ("deleted",)])
    def test_an_operation_on_an_experiment_the_project_does_not_have_is_not_found(
        self, _mock_enabled, case: str
    ) -> None:
        experiment = self._running_experiment(f"not-found-{case}", frozen=False)
        experiment_id = experiment.id if case == "deleted" else experiment.id + 1000
        Experiment.objects.filter(id=experiment.id).update(deleted=True)
        self._policy("experiment.update", conditions={})

        with patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=True):
            response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment_id}/reset/")

        assert response.status_code == 404, response.json()

    @parameterized.expand(
        [
            ("nobody_exposed", [], True, 400, "No users have been exposed"),
            (
                "too_many_exposed",
                ValidationError("This experiment has too many exposed users"),
                True,
                400,
                "too many exposed users",
            ),
            ("no_flag_access", ["00000000-0000-0000-0000-000000000001"], False, 403, None),
        ]
    )
    def test_a_freeze_that_could_only_fail_is_refused_at_once(
        self,
        _mock_enabled,
        _name: str,
        exposed: list[str] | Exception,
        can_edit_flag: bool,
        expected_status: int,
        expected_detail: str | None,
    ) -> None:
        experiment = self._running_experiment(f"freeze-refused-{_name}", frozen=False)
        self._policy("experiment.update", conditions={})

        with (
            _stub_exposure_snapshot(),
            patch.object(
                ExperimentService,
                "_fetch_exposed_person_uuids",
                **({"side_effect": exposed} if isinstance(exposed, Exception) else {"return_value": exposed}),
            ),
            patch("products.experiments.backend.experiment_service.user_can_edit_flag", return_value=can_edit_flag),
            patch("products.approvals.backend.ownership.scope_by_owner_state", return_value=True),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment.id}/freeze_exposure/")

        assert response.status_code == expected_status, response.json()
        if expected_detail is not None:
            assert expected_detail in response.json()["detail"]
        assert not ChangeRequest.objects.filter(team=self.team).exists()

    def test_a_failed_operation_records_a_readable_error(self, _mock_enabled) -> None:
        with _stub_exposure_snapshot():
            experiment = self._running_experiment("freeze-exposures-gone", frozen=False)
            change_request = self._held_operation(experiment, "freeze_exposure")

        with (
            patch.object(ExperimentService, "_fetch_exposed_person_uuids", return_value=[]),
            self.assertRaises(ApplyFailed),
        ):
            apply_change_request(change_request)

        change_request.refresh_from_db()
        assert change_request.apply_error.startswith(
            "Freeze an experiment's exposure failed: No users have been exposed to this experiment yet"
        )
