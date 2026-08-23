from uuid import UUID, uuid4

from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade import contracts
from products.tasks.backend.facade.domain_research import DomainResearch
from products.tasks.backend.facade.onboarding import _origin_key, start_onboarding_session
from products.tasks.backend.models import Task, TaskClientProvenance

MODULE = "products.tasks.backend.facade.onboarding"
QUOTA_MODULE = "products.tasks.backend.logic.services.compute_quota"

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
        def lose_the_race(**kwargs):
            self._existing_session()
            raise IntegrityError("duplicate key value violates unique constraint")

        started, create_calls = self._start(create_side_effect=lose_the_race)

        self.assertEqual(create_calls, 1)
        self.assertEqual(started, Task.objects.get(origin_key=_origin_key(self.user.id)).id)

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

    def test_a_deactivated_organization_gets_no_session(self):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])

        started, create_calls = self._start(create_side_effect=AssertionError)

        self.assertIsNone(started)
        self.assertEqual(create_calls, 0)

    def test_an_exhausted_compute_quota_gets_no_session(self):
        with (
            self.settings(TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED=True),
            patch(f"{QUOTA_MODULE}._is_posthog_code_quota_limited", return_value=True),
        ):
            started, create_calls = self._start(create_side_effect=AssertionError)

        self.assertIsNone(started)
        self.assertEqual(create_calls, 0)

    def test_a_first_request_starts_a_session_keyed_to_the_user(self):
        task_id = uuid4()

        def succeed(**kwargs):
            self.assertEqual(kwargs["origin_key"], _origin_key(self.user.id))
            self.assertEqual(kwargs["client_provenance"], TaskClientProvenance.POSTHOG_DESKTOP)
            return contracts.CreatedTaskDTO(task_id=task_id, team_id=self.team.id, latest_run=None)

        started, create_calls = self._start(create_side_effect=succeed)

        self.assertEqual(started, task_id)
        self.assertEqual(create_calls, 1)
