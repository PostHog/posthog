from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from products.mcp_store.backend.catalog import MCP_SERVER_CATALOG, CatalogEntry
from products.mcp_store.backend.catalog_sync import sync_mcp_catalog
from products.mcp_store.backend.models import (
    AUTH_TYPE_CHOICES,
    CATEGORY_CHOICES,
    MCPServerTemplate,
    normalize_mcp_icon_domain,
)
from products.mcp_store.backend.probe import ProbeResult

VALID_AUTH_TYPES = {choice for choice, _ in AUTH_TYPE_CHOICES}
VALID_CATEGORIES = {choice for choice, _ in CATEGORY_CHOICES}


def _entry(**overrides) -> CatalogEntry:
    defaults = {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "description": "Manage Linear issues.",
        "auth_type": "oauth",
        "category": "dev",
        "icon_domain": "linear.app",
    }
    defaults.update(overrides)
    return CatalogEntry(**defaults)


def _dcr_pass_probe() -> ProbeResult:
    return ProbeResult(
        reachable=True,
        speaks_mcp=True,
        auth_flavor="oauth_dcr",
        oauth_metadata={"issuer": "https://auth.linear.app", "registration_endpoint": "https://auth.linear.app/reg"},
        dcr_registered=True,
        authorize_endpoint_ok=True,
    )


class TestCatalogEntries(SimpleTestCase):
    def test_catalog_entries_are_valid(self):
        # A typo'd category/auth_type or duplicate url in a future catalog PR would otherwise
        # only surface as a failed sync in production — this is the pre-merge guard.
        urls = [entry.url for entry in MCP_SERVER_CATALOG]
        assert len(urls) == len(set(urls))
        for entry in MCP_SERVER_CATALOG:
            assert entry.auth_type in VALID_AUTH_TYPES, entry.url
            assert entry.category in VALID_CATEGORIES, entry.url
            assert entry.url.startswith("https://"), entry.url
            assert entry.name and entry.description, entry.url
            assert entry.icon_domain == normalize_mcp_icon_domain(entry.icon_domain), entry.url


class TestSyncMCPCatalog(TestCase):
    @parameterized.expand(
        [
            ("oauth_dcr_pass", _entry(), _dcr_pass_probe(), True),
            (
                "oauth_shared_needs_operator",
                _entry(),
                ProbeResult(
                    reachable=True,
                    speaks_mcp=True,
                    auth_flavor="oauth_shared",
                    oauth_metadata={"issuer": "https://auth.linear.app"},
                ),
                False,
            ),
            (
                "api_key_pass",
                _entry(auth_type="api_key"),
                ProbeResult(reachable=True, speaks_mcp=True, auth_flavor="api_key_or_unknown"),
                True,
            ),
            ("unreachable", _entry(), ProbeResult(reachable=False), False),
            # The probe saying "this is a DCR OAuth server" for a catalog entry declared api_key
            # means the entry is wrong — it must not activate even though the probe passed.
            ("flavor_disagrees_with_catalog", _entry(auth_type="api_key"), _dcr_pass_probe(), False),
        ]
    )
    def test_created_entries_gate_activation_on_probe(self, _name, entry, probe_result, expect_active):
        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server", return_value=probe_result) as probe_mock:
            counts = sync_mcp_catalog(entries=[entry])

        probe_mock.assert_called_once_with(entry.url)
        template = MCPServerTemplate.objects.get(url=entry.url)
        assert counts.created == 1
        assert template.is_active is expect_active
        assert template.name == entry.name
        assert template.icon_domain == entry.icon_domain
        if probe_result.oauth_metadata:
            assert template.oauth_metadata == probe_result.oauth_metadata
            assert template.oauth_issuer_url == probe_result.oauth_metadata.get("issuer", "")

    def test_update_touches_content_fields_but_never_operational_state(self):
        # Clobbering is_active/credentials/metadata on an operator-configured row would break
        # every existing install of that server the moment a catalog PR edits its copy.
        template = MCPServerTemplate.objects.create(
            name="Linear",
            url="https://mcp.linear.app/mcp",
            description="Old description.",
            auth_type="oauth",
            category="productivity",
            is_active=True,
            oauth_metadata={"authorization_endpoint": "https://auth.linear.app/authorize"},
            oauth_credentials={"client_id": "shared-client", "client_secret": "shhh"},
        )

        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server") as probe_mock:
            counts = sync_mcp_catalog(entries=[_entry(description="New description.", category="dev")])

        probe_mock.assert_not_called()
        template.refresh_from_db()
        assert counts.updated == 1
        assert template.description == "New description."
        assert template.category == "dev"
        assert template.is_active is True
        assert template.oauth_credentials == {"client_id": "shared-client", "client_secret": "shhh"}
        assert template.oauth_metadata == {"authorization_endpoint": "https://auth.linear.app/authorize"}

    def test_identical_entry_is_a_noop_without_probing(self):
        entry = _entry()
        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server", return_value=_dcr_pass_probe()):
            sync_mcp_catalog(entries=[entry])

        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server") as probe_mock:
            counts = sync_mcp_catalog(entries=[entry])

        probe_mock.assert_not_called()
        assert counts.unchanged == 1
        assert MCPServerTemplate.objects.filter(url=entry.url).count() == 1

    def test_skip_probe_creates_inactive(self):
        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server") as probe_mock:
            counts = sync_mcp_catalog(entries=[_entry()], skip_probe=True)

        probe_mock.assert_not_called()
        assert counts.created == 1
        assert MCPServerTemplate.objects.get(url=_entry().url).is_active is False

    def test_one_bad_entry_does_not_stop_the_sync(self):
        # category outside the model's choices makes .create raise only on full_clean, so use a
        # probe explosion instead — the loop must isolate per-entry failures.
        good = _entry()
        bad = _entry(url="https://mcp.broken.example/mcp", name="Broken")

        def _probe(url: str) -> ProbeResult:
            if "broken" in url:
                raise RuntimeError("boom")
            return _dcr_pass_probe()

        with patch("products.mcp_store.backend.catalog_sync.probe_mcp_server", side_effect=_probe):
            counts = sync_mcp_catalog(entries=[bad, good])

        assert counts.failed == 1
        assert counts.created >= 1
        assert MCPServerTemplate.objects.filter(url=good.url, is_active=True).exists()
