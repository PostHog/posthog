from __future__ import annotations

import json
from datetime import timedelta
from typing import cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalProjectProfile
from products.signals.backend.scout_harness.eval_environment.profile import (
    local_trial_project_profile,
    snapshot_project_profile,
)
from products.signals.backend.scout_harness.profile import INVENTORY_SOURCE_VERSION
from products.signals.backend.scout_harness.trial_launch import TrialContext, _write_document_once
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run


class TestLocalTrialProjectProfiles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.enterContext(self.settings(DEBUG=True, SCOUT_TRIALS_LOCAL_TEAM_ID=str(self.team.id)))
        self.profile = SignalProjectProfile.objects.for_team(self.team.id).create(
            team=self.team,
            expires_at=timezone.now() + timedelta(hours=1),
            source_version=INVENTORY_SOURCE_VERSION,
            payload={"inventory": {"project_context": {"product_description": "Saved project", "app_urls": []}}},
        )
        self.snapshot = snapshot_project_profile(self.team.id)
        self.context_id = uuid4()
        self.first = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(self.context_id)}})
        self.second = _make_run(self.team, metadata={"scout_trial": {"version": 1, "context_id": str(self.context_id)}})
        self.context = TrialContext(
            id=self.context_id,
            team_id=self.team.id,
            config_id=self.first.scout_config_id,
            user_id=self.user.id,
            created_at=timezone.now(),
            skill_name=self.first.skill_name,
            skill_version=1,
            skill_body="Inspect this project.",
            skill_origin="custom",
            allowed_tools=["emit_report"],
            capabilities={},
            runtime_adapter="codex",
            model="example-model",
            project_profile=self.snapshot,
        )
        self.enterContext(
            patch(
                "products.signals.backend.scout_harness.eval_environment.profile.load_trial_context",
                return_value=self.context,
            )
        )

    def test_starting_profile_is_shared_snapshot_even_after_background_changes(self) -> None:
        SignalProjectProfile.objects.for_team(self.team.id).filter(id=self.profile.id).update(
            payload={"inventory": {"project_context": {"product_description": "Background change", "app_urls": []}}}
        )
        first = local_trial_project_profile(ScoutTrialStore(self.first), force_refresh=False)
        second = local_trial_project_profile(ScoutTrialStore(self.second), force_refresh=False)
        assert first == second == self.snapshot
        cast(dict[str, JsonValue], first["payload"])["inventory"] = {}
        assert local_trial_project_profile(ScoutTrialStore(self.second), force_refresh=False) == self.snapshot

    def test_force_refresh_queries_real_state_but_keeps_cache_writes_and_callbacks_private(self) -> None:
        self.team.project.product_description = "Current project"
        self.team.project.save(update_fields=["product_description"])
        _authenticate_as_scout(self, scopes="signals_scout_experiment", sandbox_task_id=self.first.task_run.task_id)
        original_rows = list(SignalProjectProfile.objects.for_team(self.team.id).values())
        with (
            patch("products.signals.backend.scout_harness.profile.builders._top_events", return_value=None),
            patch("products.signals.backend.scout_harness.tools.profile.enqueue_project_profile_build") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/signals/scout/project_profile/current/", {"force_refresh": "true"}
            )
        assert response.status_code == 200, response.content
        refreshed = response.json()
        assert refreshed["profile_id"] != self.snapshot["profile_id"]
        assert refreshed["payload"]["inventory"]["project_context"]["product_description"] == "Current project"
        assert (
            local_trial_project_profile(ScoutTrialStore(self.first), force_refresh=False)["profile_id"]
            == refreshed["profile_id"]
        )
        assert local_trial_project_profile(ScoutTrialStore(self.second), force_refresh=False) == self.snapshot
        assert list(SignalProjectProfile.objects.for_team(self.team.id).values()) == original_rows
        enqueue.assert_not_called()


class TestTrialContextStorage(SimpleTestCase):
    @parameterized.expand([("without_profile", None), ("with_profile", {"payload": {}})])
    def test_stored_context_keeps_profile_key_only_when_set(
        self, _name: str, profile: dict[str, JsonValue] | None
    ) -> None:
        context = TrialContext(
            id=uuid4(),
            team_id=7,
            config_id=uuid4(),
            user_id=1,
            created_at=timezone.now(),
            skill_name="example-scout",
            skill_version=1,
            skill_body="Inspect this project.",
            skill_origin="custom",
            allowed_tools=[],
            capabilities={},
            runtime_adapter="codex",
            model="example-model",
            project_profile=profile,
        )
        with (
            patch("products.signals.backend.scout_harness.trial_launch.object_storage.read", return_value=None),
            patch("products.signals.backend.scout_harness.trial_launch.object_storage.write") as write,
        ):
            _write_document_once("example-key", context)

        stored = json.loads(write.call_args.args[1])
        assert ("project_profile" in stored) is (profile is not None)
        assert TrialContext.model_validate(stored) == context
