from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog

from products.feature_flags.backend.facade.request_lists import (
    MAX_LISTED_HOST_LENGTH,
    MAX_LISTED_HOSTS,
    MAX_LISTED_IP_LENGTH,
    MAX_LISTED_IPS,
    RequestListEntryError,
    normalize_allowed_hosts,
    normalize_listed_hosts,
    normalize_listed_ips,
)
from products.feature_flags.backend.models.team_feature_flag_policy_config import (
    TeamFeatureFlagPolicyConfig,
    team_requires_flag_tags,
)


class TestNormalizeListedHosts(SimpleTestCase):
    @parameterized.expand(
        [
            ("lowercases_and_trims", [" Example.COM. "], ["example.com"]),
            ("reduces_url_to_host", ["https://App.Example.com:8443/path?q=1"], ["app.example.com"]),
            ("dedupes_keeping_order", ["example.org", "example.com", "EXAMPLE.org"], ["example.org", "example.com"]),
            ("skips_blank_entries", ["", "  ", "example.com"], ["example.com"]),
            ("accepts_ip_literal_host", ["203.0.113.7"], ["203.0.113.7"]),
            ("accepts_localhost", ["http://localhost:3000"], ["localhost"]),
            ("encodes_idn_as_punycode", ["Bücher.example"], ["xn--bcher-kva.example"]),
            ("keeps_punycode_unchanged", ["xn--bcher-kva.example"], ["xn--bcher-kva.example"]),
            ("strips_ideographic_trailing_dot", ["example.com\u3002", "ü.com\u3002"], ["example.com", "xn--tda.com"]),
            ("backslash_in_url_reads_as_slash", ["https://example.com\\@evil.com"], ["example.com"]),
            (
                "accepts_max_after_dedupe",
                [f"host{i}.example.com" for i in range(MAX_LISTED_HOSTS)] + ["HOST0.example.com"],
                [f"host{i}.example.com" for i in range(MAX_LISTED_HOSTS)],
            ),
        ]
    )
    def test_normalizes(self, _name: str, entries: list[str], expected: list[str]) -> None:
        assert normalize_listed_hosts(entries) == expected

    @parameterized.expand(
        [
            ("wildcard", ["*.example.com"], "Enter 'example.com' instead"),
            ("path_without_scheme", ["example.com/path"], "is not a valid domain"),
            ("port_without_scheme", ["example.com:8080"], "is not a valid domain"),
            ("leading_hyphen_label", ["-example.com"], "is not a valid domain"),
            ("embedded_newline", ["example\n.com"], "is not a valid domain"),
            ("malformed_url", ["https://[example.com"], "is not a valid domain"),
            ("longer_than_253_chars", [".".join(["a" * 63] * 4)], "is not a valid domain"),
            ("invalid_idn_joiner", ["a\u200db.example"], "is not a valid domain"),
            ("invalid_punycode", ["xn--zz.com"], "is not a valid domain"),
            ("single_label", ["com"], "would match every domain that ends in .com"),
            ("too_many", [f"host{i}.example.com" for i in range(MAX_LISTED_HOSTS + 1)], "up to 100 domains"),
        ]
    )
    def test_rejects(self, _name: str, entries: list[str], message: str) -> None:
        with self.assertRaisesRegex(RequestListEntryError, message):
            normalize_listed_hosts(entries)


class TestNormalizeAllowedHosts(SimpleTestCase):
    @parameterized.expand(
        [
            ("registered_domain", "example.com"),
            ("site_on_a_shared_domain", "my-site.vercel.app"),
            ("ip_literal", "203.0.113.7"),
            ("localhost", "localhost"),
        ]
    )
    def test_accepts(self, _name: str, host: str) -> None:
        assert normalize_allowed_hosts([host]) == [host]

    @parameterized.expand(
        [
            ("shared_hosting", "Vercel.app", "example.vercel.app"),
            ("registry", "co.uk", "example.co.uk"),
            ("parent_of_wildcard_suffix", "compute.amazonaws.com", "my-site.example.compute.amazonaws.com"),
            ("distant_ancestor_of_suffixes", "amazoncognito.com", "my-site.example.amazoncognito.com"),
            (
                "ancestor_of_internationalized_suffixes",
                "xn--mre-og-romsdal-qqb.no",
                "my-site.example.xn--mre-og-romsdal-qqb.no",
            ),
        ]
    )
    def test_rejects_a_domain_that_other_people_use(self, _name: str, host: str, suggested_host: str) -> None:
        assert normalize_listed_hosts([host]) == [host.lower()]
        with self.assertRaisesRegex(RequestListEntryError, f"like {suggested_host}"):
            normalize_allowed_hosts([host])
        assert normalize_allowed_hosts([suggested_host]) == [suggested_host]


class TestNormalizeListedIps(SimpleTestCase):
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
            ("ipv4_mapped_address_as_ipv4", ["::ffff:203.0.113.7"], ["203.0.113.7"]),
            ("ipv4_mapped_range_as_ipv4", ["::ffff:203.0.113.0/120"], ["203.0.113.0/24"]),
            (
                "accepts_max_after_dedupe",
                [f"10.0.0.{i}" for i in range(MAX_LISTED_IPS)] + ["10.0.0.0/32"],
                [f"10.0.0.{i}" for i in range(MAX_LISTED_IPS)],
            ),
        ]
    )
    def test_normalizes(self, _name: str, entries: list[str], expected: list[str]) -> None:
        assert normalize_listed_ips(entries) == expected

    @parameterized.expand(
        [
            ("not_an_ip", ["example.com"], "is not a valid IP address or range"),
            ("bad_prefix", ["203.0.113.0/33"], "is not a valid IP address or range"),
            ("ipv4_everything", ["0.0.0.0/0"], "IPv4 ranges can be /8 or narrower"),
            ("ipv4_too_broad", ["192.0.0.0/7"], "IPv4 ranges can be /8 or narrower"),
            ("ipv6_everything", ["::/0"], "IPv6 ranges can be /16 or narrower"),
            ("ipv6_too_broad", ["2000::/15"], "IPv6 ranges can be /16 or narrower"),
            ("ipv4_mapped_everything", ["::ffff:0:0/96"], "IPv4 ranges can be /8 or narrower"),
            ("ipv6_scoped", ["fe80::1%eth0"], "is not a valid IP address or range"),
            ("too_many", [f"10.0.{i // 256}.{i % 256}" for i in range(MAX_LISTED_IPS + 1)], "up to 100 IP"),
        ]
    )
    def test_rejects(self, _name: str, entries: list[str], message: str) -> None:
        with self.assertRaisesRegex(RequestListEntryError, message):
            normalize_listed_ips(entries)


class TestTeamFeatureFlagPolicyConfig(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/"
        flag_patch = patch("posthog.api.team.team_config.posthog_feature_flag_enabled", return_value=True)
        self.allowlist_flag = flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def test_defaults_to_tags_not_required(self) -> None:
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"] == {
            "require_tags": False,
            "blocked_hosts": [],
            "blocked_ips": [],
            "allowed_hosts": [],
            "allowed_ips": [],
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

    def test_admin_sets_request_lists_normalized_and_logged(self) -> None:
        self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}}, format="json")
        other_hosts = [f"host{i}.example.com" for i in range(MAX_LISTED_HOSTS - 2)]
        # Each fills its column exactly. Postgres truncates an entry that is too long for its
        # varchar(n)[] column instead of raising an error, so only the read-back shows that it fits.
        longest_host = ".".join(["a" * 63] * 3 + ["b" * 61])
        longest_ip = "ffff:ffff:ffff:ffff:ffff:ffff:ffff:fffe/127"
        assert (len(longest_host), len(longest_ip)) == (MAX_LISTED_HOST_LENGTH, MAX_LISTED_IP_LENGTH)

        response = self.client.patch(
            self.url,
            {
                "feature_flag_policy_config": {
                    "blocked_hosts": ["https://Example.com/page", "", *other_hosts, longest_host, "EXAMPLE.com"],
                    "blocked_ips": ["198.51.100.42/24", "2001:db8::1", longest_ip],
                    "allowed_hosts": ["https://App.Example.org/page"],
                    "allowed_ips": ["203.0.113.9/24"],
                }
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        expected_hosts = ["example.com", *other_hosts, longest_host]
        expected_ips = ["198.51.100.0/24", "2001:db8::1", longest_ip]
        config = TeamFeatureFlagPolicyConfig.objects.get(team=self.team)
        assert config.blocked_hosts == expected_hosts
        assert config.blocked_ips == expected_ips
        assert config.allowed_hosts == ["app.example.org"]
        assert config.allowed_ips == ["203.0.113.0/24"]
        assert config.require_tags is True
        log = ActivityLog.objects.filter(team_id=self.team.id, scope="Team", activity="updated").latest("created_at")
        assert log.detail is not None
        change = log.detail["changes"][0]
        assert change["field"] == "feature_flag_policy_config"
        assert change["after"]["blocked_hosts"] == expected_hosts
        assert change["after"]["blocked_ips"] == expected_ips
        assert change["after"]["allowed_hosts"] == ["app.example.org"]
        assert change["after"]["allowed_ips"] == ["203.0.113.0/24"]

        response = self.client.patch(self.url, {"feature_flag_policy_config": {"blocked_hosts": []}}, format="json")

        assert response.status_code == status.HTTP_200_OK
        config.refresh_from_db()
        assert config.blocked_hosts == []
        assert config.blocked_ips == expected_ips
        assert config.allowed_hosts == ["app.example.org"]
        assert config.allowed_ips == ["203.0.113.0/24"]
        assert config.require_tags is True

    @parameterized.expand(
        [
            ("ip_too_broad", {"blocked_ips": ["0.0.0.0/0"]}, "/8 or narrower"),
            ("allowed_host_shared", {"allowed_hosts": ["vercel.app"]}, "like example.vercel.app"),
            ("host_malformed_url", {"blocked_hosts": ["https://[example.com"]}, "is not a valid domain"),
            (
                "hosts_over_unique_cap",
                {"blocked_hosts": [f"host{i}.example.com" for i in range(MAX_LISTED_HOSTS + 1)]},
                "up to 100 domains",
            ),
        ]
    )
    def test_invalid_request_list_entry_is_rejected(self, _name: str, policy: dict, message: str) -> None:
        response = self.client.patch(self.url, {"feature_flag_policy_config": policy}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in str(response.json())
        for field in policy:
            assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(**{field: []}).exists()

    @parameterized.expand(
        [
            ("environment_hosts", "environments", {"allowed_hosts": ["example.com", "example.org"]}),
            ("environment_ips", "environments", {"allowed_ips": ["203.0.113.7", "203.0.113.8"]}),
            ("project_ips", "projects", {"allowed_ips": ["203.0.113.7", "203.0.113.8"]}),
        ]
    )
    def test_new_allowed_entries_need_the_feature_flag(self, _name: str, scope: str, policy: dict) -> None:
        url = f"/api/{scope}/{self.team.id}/"
        self.allowlist_flag.return_value = False

        response = self.client.patch(url, {"feature_flag_policy_config": policy}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "aren't available for this project yet" in str(response.json())
        self.allowlist_flag.return_value = True
        response = self.client.patch(url, {"feature_flag_policy_config": policy}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.allowlist_flag.call_args.kwargs["team_id"] == self.team.id

        self.allowlist_flag.return_value = False
        [(field, entries)] = policy.items()
        for kept in (entries, entries[:1]):
            response = self.client.patch(url, {"feature_flag_policy_config": {field: kept}}, format="json")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["feature_flag_policy_config"][field] == kept
        response = self.client.patch(url, {"feature_flag_policy_config": policy}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        cleared = {"blocked_hosts": ["example.org"], **dict.fromkeys(policy, [])}
        response = self.client.patch(url, {"feature_flag_policy_config": cleared}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        config = TeamFeatureFlagPolicyConfig.objects.get(team=self.team)
        assert (config.blocked_hosts, config.allowed_hosts, config.allowed_ips) == (["example.org"], [], [])

    def test_member_cannot_change_policy(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            self.url,
            {
                "feature_flag_policy_config": {
                    "require_tags": True,
                    "blocked_hosts": ["example.com"],
                    "blocked_ips": ["203.0.113.7"],
                }
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert team_requires_flag_tags(self.team.id) is False
        assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(blocked_hosts=[]).exists()
        assert not TeamFeatureFlagPolicyConfig.objects.filter(team=self.team).exclude(blocked_ips=[]).exists()

    def test_patching_other_team_fields_leaves_require_tags_alone(self) -> None:
        self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        response = self.client.patch(self.url, {"name": "renamed team"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is True
