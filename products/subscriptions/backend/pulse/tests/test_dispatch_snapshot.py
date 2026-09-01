import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.subscriptions.backend.pulse.dispatch_snapshot import (
    MAX_FINALIZATION_MARGIN_SECONDS,
    MAX_WALL_CLOCK_SECONDS,
    ScheduledPulseEligibilityInput,
    _bounded_setting,
    _eligible_grant,
    build_scheduled_proactive_dispatch_manifest,
    build_scheduled_proactive_dispatch_snapshot,
    build_scheduled_proactive_dispatch_snapshots,
    resolve_scheduled_proactive_dispatch_manifest,
)
from products.subscriptions.backend.pulse.temporal.inputs import ProactiveDispatchSnapshot


class TestScheduledPulseDispatchSnapshot(SimpleTestCase):
    input = ScheduledPulseEligibilityInput(
        team_id=1,
        subscription_id=2,
        prompt="Find improvements",
        contexts=[],
        actor_id=3,
        integration_id=None,
    )

    @override_settings(PULSE_PROACTIVE_ENABLED=False)
    def test_master_off_does_not_query_or_write(self) -> None:
        with patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects") as teams:
            assert build_scheduled_proactive_dispatch_snapshot(self.input) is None
        teams.filter.assert_not_called()

    @override_settings(PULSE_PROACTIVE_ENABLED=True)
    def test_missing_config_is_ineligible(self) -> None:
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team"
            ) as configs,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            configs.return_value.filter.return_value.first.return_value = None
            assert build_scheduled_proactive_dispatch_snapshot(self.input) is None

    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_WALL_CLOCK_SECONDS=MAX_WALL_CLOCK_SECONDS * 2,
        PULSE_FINALIZATION_MARGIN_SECONDS=MAX_FINALIZATION_MARGIN_SECONDS * 2,
    )
    def test_eligible_snapshot_is_ref_only_bounded_and_retry_stable(self) -> None:
        config = MagicMock(enabled=True, create_draft_pr=False, repository=None, public_research_enabled=True)
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team"
            ) as configs,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            configs.return_value.filter.return_value.first.return_value = config
            first = build_scheduled_proactive_dispatch_snapshot(self.input)
            second = build_scheduled_proactive_dispatch_snapshot(self.input)

        assert first is not None and second == first
        assert first.wall_clock_budget_seconds == MAX_WALL_CLOCK_SECONDS
        assert first.finalization_margin_seconds == MAX_FINALIZATION_MARGIN_SECONDS
        assert first.config_snapshot_ref.startswith("subscriptions/pulse/dispatch-snapshots/v1/1/2/")
        assert len(write.call_args.args[1]) <= 32 * 1024
        assert write.call_args_list[0].args[0] == write.call_args_list[1].args[0]

    @override_settings(PULSE_WALL_CLOCK_SECONDS=0)
    def test_limits_have_positive_hard_bounds(self) -> None:
        assert _bounded_setting("PULSE_WALL_CLOCK_SECONDS", 10, 120, minimum=60) == 60

    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_MAX_AGENT_CONTEXT_TOKENS=1_000_000,
        PULSE_OUTCOME_READOUT_ENABLED=True,
        PULSE_MAX_DUE_READOUTS_PER_DELIVERY=2,
    )
    def test_snapshot_persists_the_server_owned_agent_context_window_cap(self) -> None:
        config = MagicMock(enabled=True, create_draft_pr=False, repository=None, public_research_enabled=True)
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team"
            ) as configs,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            configs.return_value.filter.return_value.first.return_value = config

            assert build_scheduled_proactive_dispatch_snapshot(self.input) is not None

        snapshot = json.loads(write.call_args.args[1])
        assert snapshot["limits"]["max_agent_context_tokens"] == 1_000_000
        assert snapshot["flags"]["allow_outcome_readouts"] is True
        assert snapshot["limits"]["max_due_readouts"] == 2

    @override_settings(PULSE_PROACTIVE_ENABLED=True)
    def test_batch_snapshot_reuses_live_repository_authorization_for_equivalent_grants(self) -> None:
        team = MagicMock(id=1)
        actor = MagicMock(id=3, is_active=True)
        first_config = MagicMock(
            id=10,
            team_id=1,
            subscription_id=2,
            enabled=True,
            create_draft_pr=True,
            repository="posthog/posthog",
            public_research_enabled=True,
        )
        second_config = MagicMock(
            id=11,
            team_id=1,
            subscription_id=3,
            enabled=True,
            create_draft_pr=True,
            repository="posthog/posthog",
            public_research_enabled=True,
        )
        first_grant = MagicMock(
            id=20,
            team_id=1,
            config_id=10,
            active=True,
            revoked_at=None,
            authorizer_id=3,
            automation_owner_id=3,
            repository="posthog/posthog",
            integration_id=4,
            repository_installation_id="installation",
            grant_version=1,
            capabilities={"draft_pr": True},
        )
        second_grant = MagicMock(
            id=21,
            team_id=1,
            config_id=11,
            active=True,
            revoked_at=None,
            authorizer_id=3,
            automation_owner_id=3,
            repository="posthog/posthog",
            integration_id=4,
            repository_installation_id="installation",
            grant_version=1,
            capabilities={"draft_pr": True},
        )
        first_config.repository_grant = first_grant
        second_config.repository_grant = second_grant
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.all_teams.filter"
            ) as configs,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.repository_grants_authorizations_are_live",
                return_value={20: True, 21: True},
            ) as authorize,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write"),
        ):
            teams.return_value.in_bulk.return_value = {1: team}
            users.return_value.in_bulk.return_value = {3: actor}
            configs.return_value.select_related.return_value = [first_config, second_config]

            snapshots = build_scheduled_proactive_dispatch_snapshots(
                [
                    ScheduledPulseEligibilityInput(
                        team_id=1,
                        subscription_id=2,
                        prompt="First",
                        contexts=[],
                        actor_id=3,
                        integration_id=None,
                        contexts_authorized=True,
                    ),
                    ScheduledPulseEligibilityInput(
                        team_id=1,
                        subscription_id=3,
                        prompt="Second",
                        contexts=[],
                        actor_id=3,
                        integration_id=None,
                        contexts_authorized=True,
                    ),
                ]
            )

        assert snapshots[2] is not None
        assert snapshots[3] is not None
        authorize.assert_called_once_with([first_grant, second_grant])

    @override_settings(PULSE_PROACTIVE_ENABLED=True, OBJECT_STORAGE_BUCKET="test-bucket")
    def test_schedule_manifest_round_trips_one_snapshot_by_subscription(self) -> None:
        snapshot = ProactiveDispatchSnapshot(
            version=1,
            enabled=True,
            config_snapshot_ref="subscriptions/pulse/dispatch-snapshots/v1/1/2/test.json",
            wall_clock_budget_seconds=3600,
            finalization_margin_seconds=300,
        )
        with (
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.build_scheduled_proactive_dispatch_snapshots",
                return_value={2: snapshot, 3: None},
            ) as build_snapshots,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            manifest_ref = build_scheduled_proactive_dispatch_manifest([self.input])

        assert manifest_ref is not None
        assert manifest_ref.startswith("subscriptions/pulse/dispatch-manifests/v1/")
        build_snapshots.assert_called_once_with([self.input])
        encoded_entry = write.call_args.args[1]
        with patch(
            "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes",
            return_value=encoded_entry,
        ) as read_entry:
            assert resolve_scheduled_proactive_dispatch_manifest(manifest_ref, 1, 2) == snapshot
            assert resolve_scheduled_proactive_dispatch_manifest(manifest_ref, 1, 3) is None
        assert read_entry.call_args_list[0].args[0] == f"{manifest_ref}/2.json"

    @override_settings(OBJECT_STORAGE_BUCKET="test-bucket")
    def test_schedule_manifest_rejects_content_that_does_not_match_its_reference(self) -> None:
        manifest_ref = f"subscriptions/pulse/dispatch-manifests/v1/{'0' * 64}"
        with patch(
            "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes",
            return_value=b'{"version":1,"snapshots":{}}',
        ):
            assert resolve_scheduled_proactive_dispatch_manifest(manifest_ref, 1, 2) is None

    @parameterized.expand(
        [
            ("inactive", "active", False),
            ("revoked", "revoked_at", MagicMock()),
            ("missing_capability", "capabilities", {}),
            ("missing_installation", "repository_installation_id", ""),
        ]
    )
    def test_repository_grant_must_retain_every_authority_binding(
        self, _name: str, field: str, invalid_value: object
    ) -> None:
        config = MagicMock(id=10, repository="PostHog/posthog", repository_grant_id=MagicMock())
        grant = MagicMock(
            active=True,
            revoked_at=None,
            config_id=10,
            authorizer_id=3,
            automation_owner_id=3,
            repository="posthog/posthog",
            integration_id=4,
            repository_installation_id="installation",
            capabilities={"draft_pr": True},
        )
        setattr(grant, field, invalid_value)
        query = MagicMock()
        query.filter.return_value.first.return_value = grant
        with (
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.RepositoryGrant.objects.for_team",
                return_value=query,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.repository_grant_authorization_is_live",
                return_value=True,
            ),
        ):
            result = _eligible_grant(
                input=ScheduledPulseEligibilityInput(
                    team_id=1,
                    subscription_id=2,
                    prompt="Find improvements",
                    contexts=[],
                    actor_id=3,
                    integration_id=4,
                ),
                config=config,
            )

        assert result is None

    @override_settings(PULSE_PROACTIVE_ENABLED=True, PULSE_DRAFT_PR_ENABLED=True)
    def test_scheduled_snapshot_retains_cross_editor_repository_grant(self) -> None:
        config = MagicMock(
            id=10,
            enabled=True,
            create_draft_pr=True,
            repository="PostHog/posthog",
            repository_grant_id=20,
            public_research_enabled=True,
        )
        grant = MagicMock(
            id=20,
            active=True,
            revoked_at=None,
            config_id=10,
            authorizer_id=4,
            automation_owner_id=4,
            repository="posthog/posthog",
            integration_id=5,
            repository_installation_id="installation-5",
            grant_version=1,
            capabilities={"draft_pr": True},
        )
        input = ScheduledPulseEligibilityInput(
            team_id=1,
            subscription_id=2,
            prompt="Find improvements",
            contexts=[],
            actor_id=3,
            integration_id=999,
        )
        config_query = MagicMock()
        config_query.filter.return_value.first.return_value = config
        grant_query = MagicMock()
        grant_query.filter.return_value.first.return_value = grant
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team",
                return_value=config_query,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.RepositoryGrant.objects.for_team",
                return_value=grant_query,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.repository_grant_authorization_is_live",
                return_value=True,
            ) as grant_authorized,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            assert build_scheduled_proactive_dispatch_snapshot(input) is not None

        snapshot = json.loads(write.call_args.args[1])
        assert snapshot["actor_id"] == 3
        assert snapshot["integration_id"] == 999
        assert snapshot["automation_owner_id"] == 4
        assert snapshot["repository_grant"]["integration_id"] == 5
        grant_authorized.assert_called_once_with(team_id=1, grant=grant)

    @parameterized.expand([("enabled", True, True), ("opted_out", False, False)])
    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_PUBLIC_RESEARCH_ENABLED=True,
        FIRECRAWL_API_KEY="test-firecrawl-key",
    )
    def test_public_research_follows_the_subscription_opt_out(
        self, _name: str, public_research_enabled: bool, expected: bool
    ) -> None:
        config = MagicMock(
            enabled=True,
            create_draft_pr=False,
            repository=None,
            public_research_enabled=public_research_enabled,
        )
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team"
            ) as configs,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes", return_value=None
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            configs.return_value.filter.return_value.first.return_value = config

            assert build_scheduled_proactive_dispatch_snapshot(self.input) is not None

        snapshot = json.loads(write.call_args.args[1])
        assert snapshot["public_research_enabled"] is public_research_enabled
        assert snapshot["flags"]["allow_public_research"] is expected

    @override_settings(PULSE_PROACTIVE_ENABLED=True)
    def test_existing_snapshot_bytes_must_match_the_content_address(self) -> None:
        config = MagicMock(enabled=True, create_draft_pr=False, repository=None, public_research_enabled=True)
        with (
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.Team.objects.filter") as teams,
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.subscription_snapshot_contexts_are_authorized",
                return_value=True,
            ),
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.ProactiveSubscriptionConfig.objects.for_team"
            ) as configs,
            patch(
                "products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.read_bytes",
                return_value=b"different",
            ),
            patch("products.subscriptions.backend.pulse.dispatch_snapshot.object_storage.write") as write,
        ):
            teams.return_value.first.return_value = MagicMock()
            users.return_value.first.return_value = MagicMock()
            configs.return_value.filter.return_value.first.return_value = config

            assert build_scheduled_proactive_dispatch_snapshot(self.input) is None

        write.assert_not_called()
