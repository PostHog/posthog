from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.test.utils import override_settings

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade import contracts
from products.tasks.backend.facade.domain_research import DomainResearch
from products.tasks.backend.facade.onboarding import _origin_key, _session_enabled, start_onboarding_session
from products.tasks.backend.facade.onboarding_canvas import TeachingCanvas
from products.tasks.backend.models import Task, TaskClientProvenance

MODULE = "products.tasks.backend.facade.onboarding"

NOT_CONFIGURED = DomainResearch(outcome="not_configured", url="https://northwind.example/")


class TestOnboardingSessionIdempotency(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Northwind")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="ada@northwind.example", distinct_id="ada-distinct")
        self.channel_id = uuid4()

    def _existing_session(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="Getting set up",
            description="prompt",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            origin_key=_origin_key(self.user.id),
        )

    @override_settings(DEBUG=False)
    def test_both_spaces_flags_must_be_enabled(self) -> None:
        with patch("posthoganalytics.feature_enabled", side_effect=[True, False]) as feature_enabled:
            self.assertFalse(_session_enabled(self.team, self.user))

        self.assertEqual(
            [call.args[0] for call in feature_enabled.call_args_list],
            ["code-spaces-layout", "project-bluebird"],
        )

    def _start(self, create_side_effect) -> tuple[UUID | None, int]:
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch(f"{MODULE}.find_general_channel_id", return_value=self.channel_id),
            patch(f"{MODULE}.research_domain", return_value=NOT_CONFIGURED),
            patch(f"{MODULE}.create_and_run_task", side_effect=create_side_effect) as create,
        ):
            return start_onboarding_session(self.team, self.user), create.call_count

    def test_a_repeated_request_returns_the_session_it_already_started(self):
        existing = self._existing_session()

        started, create_calls = self._start(create_side_effect=AssertionError)

        self.assertEqual(started, existing.id)
        self.assertEqual(create_calls, 0)

    def test_a_racing_request_returns_the_session_the_winner_started(self):
        winner = self._existing_session()
        # The winner commits in another transaction, which a TestCase cannot produce: the create
        # now runs inside transaction.atomic(), so a row written by the mock would roll back with
        # it. Standing in for the second connection is what the two reads are for.
        with patch(f"{MODULE}._started_session_id", side_effect=[None, winner.id]) as lookup:
            started, create_calls = self._start(create_side_effect=IntegrityError("duplicate key"))

        self.assertEqual(create_calls, 1)
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(started, winner.id)

    def test_a_task_that_squatted_the_key_is_not_mistaken_for_the_session(self):
        Task.objects.create(
            team=self.team,
            title="Someone else's task",
            description="prompt",
            origin_product=Task.OriginProduct.WORKFLOW,
            created_by=self.user,
            origin_key=_origin_key(self.user.id),
        )

        with self.assertRaises(IntegrityError):
            self._start(create_side_effect=IntegrityError("duplicate key"))

    @parameterized.expand(
        [
            ("free", [], "@cf/zai-org/glm-5.2"),
            (
                "paid",
                [{"key": AvailableFeature.POSTHOG_CODE_USAGE, "name": "PostHog Desktop usage billing"}],
                "claude-opus-4-8",
            ),
        ]
    )
    def test_a_first_request_starts_an_entitled_session_keyed_to_the_user(
        self, _name: str, available_product_features: list[dict[str, str]], expected_model: str
    ) -> None:
        self.organization.available_product_features = available_product_features
        self.organization.save(update_fields=["available_product_features"])
        task_id = uuid4()

        def succeed(**kwargs):
            self.assertEqual(kwargs["origin_key"], _origin_key(self.user.id))
            self.assertEqual(kwargs["client_provenance"], TaskClientProvenance.POSTHOG_DESKTOP)
            self.assertEqual(kwargs["model"], expected_model)
            self.assertTrue(kwargs["title_manually_set"])
            return contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        started, create_calls = self._start(create_side_effect=succeed)

        self.assertEqual(started, task_id)
        self.assertEqual(create_calls, 1)

    def test_seeding_the_tour_failing_does_not_block_the_session(self) -> None:
        task_id = uuid4()

        def succeed(**kwargs: Any) -> contracts.CreatedTaskDTO:
            self.assertNotIn("open_canvas", kwargs["description"])
            return contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        with patch(f"{MODULE}.ensure_teaching_canvas", side_effect=RuntimeError("canvas app down")):
            started, create_calls = self._start(create_side_effect=succeed)

        self.assertEqual(started, task_id)
        self.assertEqual(create_calls, 1)

    def test_an_invalid_managed_prompt_uses_the_bundled_prompt_and_captures_the_fallback(self) -> None:
        task_id = uuid4()

        def succeed(**kwargs: Any) -> contracts.CreatedTaskDTO:
            self.assertIn("<followup>", kwargs["description"])
            self.assertNotIn("invalid managed prompt", kwargs["description"])
            return contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        with (
            patch(
                f"{MODULE}.load_onboarding_prompt",
                return_value=SimpleNamespace(prompt="invalid managed prompt", source="remote", version=7),
            ),
            patch(f"{MODULE}.posthoganalytics.capture") as capture,
        ):
            started, _ = self._start(create_side_effect=succeed)

        self.assertEqual(started, task_id)
        fallback = next(
            call for call in capture.call_args_list if call.kwargs["event"] == "Onboarding prompt fallback used"
        )
        self.assertEqual(fallback.kwargs["properties"]["reason"], "missing_placeholders")
        self.assertEqual(
            fallback.kwargs["properties"]["missing_placeholders"],
            ("brief", "channel_id", "followup", "homepage"),
        )

    def test_domain_research_outcome_is_captured_for_the_started_session(self) -> None:
        task_id = uuid4()
        created = contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        with patch(f"{MODULE}.posthoganalytics.capture") as capture:
            started, _ = self._start(create_side_effect=lambda **_kwargs: created)

        self.assertEqual(started, task_id)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["event"], "Onboarding domain research completed")
        self.assertEqual(
            capture.call_args.kwargs["properties"],
            {"task_id": str(task_id), "outcome": "not_configured"},
        )

    def test_a_seeded_tour_reaches_the_prompt_with_both_ids(self) -> None:
        task_id = uuid4()
        teaching = TeachingCanvas(channel_id=self.channel_id, canvas_id=uuid4())

        def succeed(**kwargs: Any) -> contracts.CreatedTaskDTO:
            self.assertIn(f"channel_id `{teaching.channel_id}`", kwargs["description"])
            self.assertIn(f"canvas_id `{teaching.canvas_id}`", kwargs["description"])
            return contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        with patch(f"{MODULE}.ensure_teaching_canvas", return_value=teaching):
            started, create_calls = self._start(create_side_effect=succeed)

        self.assertEqual(started, task_id)
        self.assertEqual(create_calls, 1)
