from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog

from products.feature_flags.backend.models.team_feature_flag_policy_config import (
    MAX_BLOCKED_HOSTS,
    MAX_BLOCKED_IPS,
    BlocklistEntryError,
    TeamFeatureFlagPolicyConfig,
    normalize_blocked_hosts,
    normalize_blocked_ips,
    team_requires_flag_tags,
)


class TestNormalizeBlockedHosts(SimpleTestCase):
    @parameterized.expand(
        [
            ("lowercases_and_trims", [" Example.COM. "], ["example.com"]),
            ("reduces_url_to_host", ["https://App.Example.com:8443/path?q=1"], ["app.example.com"]),
            ("dedupes_keeping_order", ["example.org", "example.com", "EXAMPLE.org"], ["example.org", "example.com"]),
            ("skips_blank_entries", ["", "  ", "example.com"], ["example.com"]),
            ("accepts_ip_literal_host", ["203.0.113.7"], ["203.0.113.7"]),
        ]
    )
    def test_normalizes(self, _name: str, entries: list[str], expected: list[str]) -> None:
        assert normalize_blocked_hosts(entries) == expected

    @parameterized.expand(
        [
            ("wildcard", ["*.example.com"], "Enter 'example.com' instead"),
            ("path_without_scheme", ["example.com/path"], "is not a valid domain"),
            ("port_without_scheme", ["example.com:8080"], "is not a valid domain"),
            ("leading_hyphen_label", ["-example.com"], "is not a valid domain"),
            ("too_many", [f"host{i}.example.com" for i in range(MAX_BLOCKED_HOSTS + 1)], "up to 100 domains"),
        ]
    )
    def test_rejects(self, _name: str, entries: list[str], message: str) -> None:
        with self.assertRaisesRegex(BlocklistEntryError, message):
            normalize_blocked_hosts(entries)


class TestNormalizeBlockedIps(SimpleTestCase):
    @parameterized.expand(
        [
            ("ipv4_address", ["203.0.113.7"], ["203.0.113.7"]),
            ("ipv4_full_prefix_drops_suffix", ["203.0.113.7/32"], ["203.0.113.7"]),
            ("ipv4_cidr_drops_host_bits", ["198.51.100.42/24"], ["198.51.100.0/24"]),
            ("ipv4_widest_allowed", ["10.1.2.3/8"], ["10.0.0.0/8"]),
            ("ipv6_address_compressed", ["2001:0db8:0000:0000:0000:0000:0000:0001"], ["2001:db8::1"]),
            ("ipv6_cidr", ["2001:db8:abcd:12::/48"], ["2001:db8:abcd::/48"]),
            ("ipv6_widest_allowed", ["2001:db8::/16"], ["2001::/16"]),
            ("dedupes_after_normalizing", ["203.0.113.7", " 203.0.113.7/32 ", ""], ["203.0.113.7"]),
        ]
    )
    def test_normalizes(self, _name: str, entries: list[str], expected: list[str]) -> None:
        assert normalize_blocked_ips(entries) == expected

    @parameterized.expand(
        [
            ("not_an_ip", ["example.com"], "is not a valid IP address or range"),
            ("bad_prefix", ["203.0.113.0/33"], "is not a valid IP address or range"),
            ("ipv4_everything", ["0.0.0.0/0"], "IPv4 ranges can be /8 or narrower"),
            ("ipv4_too_broad", ["192.0.0.0/7"], "IPv4 ranges can be /8 or narrower"),
            ("ipv6_everything", ["::/0"], "IPv6 ranges can be /16 or narrower"),
            ("ipv6_too_broad", ["2000::/15"], "IPv6 ranges can be /16 or narrower"),
            ("too_many", [f"10.0.{i // 256}.{i % 256}" for i in range(MAX_BLOCKED_IPS + 1)], "up to 100 IP"),
        ]
    )
    def test_rejects(self, _name: str, entries: list[str], message: str) -> None:
        with self.assertRaisesRegex(BlocklistEntryError, message):
            normalize_blocked_ips(entries)


class TestTeamFeatureFlagPolicyConfig(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/"

    def test_defaults_to_tags_not_required(self) -> None:
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"] == {
            "require_tags": False,
            "blocked_hosts": [],
            "blocked_ips": [],
        }

    def test_admin_can_toggle_require_tags(self) -> None:
        response = self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is True
        assert TeamFeatureFlagPolicyConfig.objects.get(team=self.team).require_tags is True

        response = self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": False}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is False
        assert TeamFeatureFlagPolicyConfig.objects.get(team=self.team).require_tags is False

    def test_admin_sets_request_blocklist_normalized_and_logged(self) -> None:
        response = self.client.patch(
            self.url,
            {
                "feature_flag_policy_config": {
                    "blocked_hosts": ["https://Example.com/page"],
                    "blocked_ips": ["198.51.100.42/24", "2001:db8::1"],
                }
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        config = TeamFeatureFlagPolicyConfig.objects.get(team=self.team)
        assert config.blocked_hosts == ["example.com"]
        assert config.blocked_ips == ["198.51.100.0/24", "2001:db8::1"]
        assert config.require_tags is False
        log = ActivityLog.objects.filter(team_id=self.team.id, scope="Team", activity="updated").latest("created_at")
        assert log.detail is not None
        change = log.detail["changes"][0]
        assert change["field"] == "feature_flag_policy_config"
        assert change["after"]["blocked_hosts"] == ["example.com"]
        assert change["after"]["blocked_ips"] == ["198.51.100.0/24", "2001:db8::1"]

    def test_invalid_blocked_ip_is_rejected(self) -> None:
        response = self.client.patch(
            self.url, {"feature_flag_policy_config": {"blocked_ips": ["0.0.0.0/0"]}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "/8 or narrower" in str(response.json())
        assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(blocked_ips=[]).exists()

    @parameterized.expand(
        [
            ("require_tags", {"require_tags": True}),
            ("blocked_hosts", {"blocked_hosts": ["example.com"]}),
            ("blocked_ips", {"blocked_ips": ["203.0.113.7"]}),
        ]
    )
    def test_member_cannot_change_policy(self, _name: str, policy: dict) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(self.url, {"feature_flag_policy_config": policy}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert team_requires_flag_tags(self.team.id) is False
        assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(blocked_hosts=[]).exists()
        assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(blocked_ips=[]).exists()

    def test_patching_other_team_fields_leaves_require_tags_alone(self) -> None:
        self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        response = self.client.patch(self.url, {"name": "renamed team"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is True
