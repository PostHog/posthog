from posthog.test.base import BaseTest

from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.growth.backend.sdk_version_snapshot import (
    SDK_LIBS_PROPERTY,
    SDK_VERSION_KEYS_PROPERTY,
    SDK_VERSIONS_UPDATED_AT_PROPERTY,
    _group_properties,
    _roll_up_to_groups,
    snapshot_sdk_versions_to_groups,
)

MODULE = "products.growth.backend.sdk_version_snapshot"


class TestGroupProperties(BaseTest):
    def test_group_properties_sorts_keys_and_derives_libs(self):
        props = _group_properties({"posthog-php@3.4.0", "web@1.2.0", "posthog-php@3.3.0"}, "2026-06-03T00:00:00")

        assert props[SDK_VERSION_KEYS_PROPERTY] == ["posthog-php@3.3.0", "posthog-php@3.4.0", "web@1.2.0"]
        assert props[SDK_LIBS_PROPERTY] == ["posthog-php", "web"]
        assert props[SDK_VERSIONS_UPDATED_AT_PROPERTY] == "2026-06-03T00:00:00"


class TestRollUpToGroups(BaseTest):
    def test_unions_teams_into_org_and_customer_groups(self):
        self.organization.customer_id = "cus_123"
        self.organization.save()
        team_a = self.team
        team_b = Team.objects.create(organization=self.organization, name="b")

        team_keys = {
            team_a.id: {"web@1.0.0", "posthog-php@3.4.0"},
            team_b.id: {"web@2.0.0"},
        }

        org_keys, customer_keys = _roll_up_to_groups(team_keys)

        assert org_keys == {str(self.organization.id): {"web@1.0.0", "web@2.0.0", "posthog-php@3.4.0"}}
        assert customer_keys == {"cus_123": {"web@1.0.0", "web@2.0.0", "posthog-php@3.4.0"}}

    def test_org_without_customer_id_skips_customer_group(self):
        self.organization.customer_id = None
        self.organization.save()

        org_keys, customer_keys = _roll_up_to_groups({self.team.id: {"web@1.0.0"}})

        assert org_keys == {str(self.organization.id): {"web@1.0.0"}}
        assert customer_keys == {}

    def test_unions_orgs_sharing_a_customer_id(self):
        self.organization.customer_id = "cus_shared"
        self.organization.save()
        other_org = Organization.objects.create(name="other", customer_id="cus_shared")
        other_team = Team.objects.create(organization=other_org, name="other")

        team_keys = {self.team.id: {"web@1.0.0"}, other_team.id: {"posthog-go@1.5.0"}}

        _, customer_keys = _roll_up_to_groups(team_keys)

        assert customer_keys == {"cus_shared": {"web@1.0.0", "posthog-go@1.5.0"}}

    def test_excludes_demo_and_internal_metrics_teams(self):
        internal_org = Organization.objects.create(name="internal", for_internal_metrics=True)
        internal_team = Team.objects.create(organization=internal_org, name="internal")
        demo_team = Team.objects.create(organization=self.organization, name="demo", is_demo=True)

        team_keys = {
            self.team.id: {"web@1.0.0"},
            internal_team.id: {"web@9.9.9"},
            demo_team.id: {"web@8.8.8"},
        }

        org_keys, _ = _roll_up_to_groups(team_keys)

        assert org_keys == {str(self.organization.id): {"web@1.0.0"}}

    def test_empty_team_keys_returns_empty(self):
        assert _roll_up_to_groups({}) == ({}, {})


class TestSnapshotSdkVersionsToGroups(BaseTest):
    @patch(f"{MODULE}.get_ph_client")
    @patch(f"{MODULE}._fetch_team_sdk_keys")
    def test_writes_org_and_customer_group_properties(self, mock_fetch: MagicMock, mock_get_client: MagicMock):
        self.organization.customer_id = "cus_123"
        self.organization.save()
        mock_fetch.return_value = {self.team.id: {"posthog-php@3.4.0", "web@1.0.0"}}
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        written = snapshot_sdk_versions_to_groups()

        assert written == {"organizations": 1, "customers": 1}
        assert mock_client.group_identify.call_count == 2
        org_call = next(c for c in mock_client.group_identify.call_args_list if c.kwargs["group_type"] == "organization")
        assert org_call.kwargs["group_key"] == str(self.organization.id)
        assert org_call.kwargs["properties"][SDK_VERSION_KEYS_PROPERTY] == ["posthog-php@3.4.0", "web@1.0.0"]

    @patch(f"{MODULE}.get_ph_client")
    @patch(f"{MODULE}._fetch_team_sdk_keys")
    def test_no_client_is_a_noop(self, mock_fetch: MagicMock, mock_get_client: MagicMock):
        mock_fetch.return_value = {self.team.id: {"web@1.0.0"}}
        mock_get_client.return_value = None

        assert snapshot_sdk_versions_to_groups() == {"organizations": 0, "customers": 0}

    @patch(f"{MODULE}.get_ph_client")
    @patch(f"{MODULE}._fetch_team_sdk_keys")
    def test_group_identify_failure_does_not_abort_run(self, mock_fetch: MagicMock, mock_get_client: MagicMock):
        self.organization.customer_id = "cus_123"
        self.organization.save()
        mock_fetch.return_value = {self.team.id: {"web@1.0.0"}}
        mock_client = MagicMock()
        mock_client.group_identify.side_effect = [Exception("boom"), None]
        mock_get_client.return_value = mock_client

        written = snapshot_sdk_versions_to_groups()

        # organization write raised, customer write still attempted and succeeded
        assert written == {"organizations": 0, "customers": 1}
