from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import ANY, Integration
from posthog.models.integration.auth_types import default_auth_type

from products.integrations.backend.facade.api import IntegrationManager, register_source_kinds, register_usage_provider
from products.integrations.backend.facade.api_accessors import IntegrationReader
from products.integrations.backend.facade.contracts import (
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationUsage,
    UnknownIntegrationKind,
    UnsupportedAuthType,
    UnsupportedIntegrationFilter,
)
from products.integrations.backend.facade.enums import AuthType
from products.integrations.backend.logic import usages

MARKER = "warehouse_source_type"

# name -> (kind, config). The name is also the external id.
ROWS: dict[str, tuple[str, dict[str, Any]]] = {
    "github_oauth": ("github", {"account": {"name": "a"}}),
    "github_token": ("github", {"auth_type": "token", "account": {"name": "a"}}),
    "slack_oauth": ("slack", {}),
    "stripe_oauth": ("stripe", {}),
    "stripe_token": ("stripe", {"auth_type": "token"}),
    "stripe_source": ("stripe", {"auth_type": "token", MARKER: "Stripe"}),
    "postgres": ("postgresql", {"host": "db.example.com"}),
    "ably_source": ("ably", {MARKER: "Ably"}),
}


@contextmanager
def _usage_providers(*providers: usages.UsageProvider) -> Iterator[None]:
    with patch.object(usages, "_registered", []), patch.object(usages, "_product_providers", list(providers)):
        yield


class TestIntegrationAccessors(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.rows = {
            name: Integration.objects._with_auth(ANY).create(
                team=self.team, kind=kind, integration_id=name, config=config
            )
            for name, (kind, config) in ROWS.items()
        }
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other_row = Integration.objects._with_auth(ANY).create(
            team=self.other_team, kind="github", integration_id="github_oauth", config={}
        )

    def _names(self, rows: list[Integration]) -> set[str]:
        return {row.integration_id for row in rows if row.team_id == self.team.id and row.integration_id}

    @parameterized.expand(
        [
            ("single_auth_default", lambda: IntegrationManager.github.oauth, {"github_oauth"}),
            ("single_auth_non_default", lambda: IntegrationManager.github.token, {"github_token"}),
            ("kind_any", lambda: IntegrationManager.github.any, {"github_oauth", "github_token"}),
            ("skips_source_rows", lambda: IntegrationManager.stripe.token, {"stripe_token"}),
            ("kind_any_skips_source_rows", lambda: IntegrationManager.stripe.any, {"stripe_oauth", "stripe_token"}),
            ("credentials_default", lambda: IntegrationManager.postgresql.credentials, {"postgres"}),
            ("everything", lambda: IntegrationManager.any, set(ROWS)),
            ("source_of_a_catalogue_kind", lambda: IntegrationManager.source("stripe").token, {"stripe_source"}),
            ("source_any", lambda: IntegrationManager.source("stripe").any, {"stripe_source"}),
            ("source_of_a_registered_kind", lambda: IntegrationManager.source("ably").token, {"ably_source"}),
            ("source_other_auth_type", lambda: IntegrationManager.source("ably").credentials, set()),
            (
                "several_kinds",
                lambda: IntegrationManager.kinds("github", "slack"),
                {"github_oauth", "github_token", "slack_oauth"},
            ),
        ]
    )
    def test_list_returns_only_rows_in_scope(
        self, _name: str, accessor: Callable[[], IntegrationReader], expected: set[str]
    ) -> None:
        assert self._names(accessor().list(self.team.id)) == expected

    @parameterized.expand(
        [
            ("other_auth_type", lambda: IntegrationManager.github.oauth, "github_token"),
            ("source_row_through_named_accessor", lambda: IntegrationManager.stripe.any, "stripe_source"),
            ("named_row_through_source_accessor", lambda: IntegrationManager.source("stripe").token, "stripe_token"),
            ("other_kind", lambda: IntegrationManager.slack.oauth, "github_oauth"),
        ]
    )
    def test_get_raises_for_a_row_out_of_scope(
        self, _name: str, accessor: Callable[[], IntegrationReader], row_name: str
    ) -> None:
        with self.assertRaises(IntegrationNotFound):
            accessor().get(self.team.id, self.rows[row_name].id)

    @parameterized.expand([("missing_id", 10**9), ("not_a_number", "abc"), ("none", None)])
    def test_get_raises_for_a_bad_id(self, _name: str, row_id: Any) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.any.get(self.team.id, row_id)

    def test_get_does_not_cross_teams(self) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.get(self.team.id, self.other_row.id)

        assert IntegrationManager.github.oauth.get(self.other_team.id, self.other_row.id) == self.other_row

    def test_get_many_drops_ids_out_of_scope(self) -> None:
        ids = [self.rows["github_oauth"].id, self.rows["github_token"].id, self.other_row.id, 10**9]

        assert IntegrationManager.github.oauth.get_many(self.team.id, ids) == {
            self.rows["github_oauth"].id: self.rows["github_oauth"]
        }

    @parameterized.expand(
        [
            ("external_id", {"external_id": "github_token"}, "github_token"),
            ("nested_config_value", {"where": {"account": {"name": "a"}}}, None),
            ("scalar_config_value", {"where": {"auth_type_hint": None}}, None),
            ("oldest_without_filters", {}, "github_oauth"),
            ("no_match", {"external_id": "missing"}, None),
        ]
    )
    def test_find(self, _name: str, kwargs: dict[str, Any], expected: str | None) -> None:
        if isinstance(next(iter(kwargs.get("where", {}).values()), None), dict):
            with self.assertRaises(UnsupportedIntegrationFilter):
                IntegrationManager.github.any.find(self.team.id, **kwargs)
            return
        row = IntegrationManager.github.any.find(self.team.id, **kwargs)

        assert (row.integration_id if row else None) == expected

    @parameterized.expand(
        [
            ("string", {"host": "db.example.com"}, True),
            ("string_mismatch", {"host": "other.example.com"}, False),
            ("missing_key_matches_none", {"port": None}, False),
            ("key_named_like_a_lookup", {"contains": "x"}, False),
        ]
    )
    def test_exists_compares_config_keys_for_equality(self, _name: str, where: dict[str, Any], expected: bool) -> None:
        assert IntegrationManager.postgresql.credentials.exists(self.team.id, where=where) is expected

    def test_find_returns_the_oldest_row_and_list_can_reverse(self) -> None:
        newer = IntegrationManager.github.oauth.create(self.team.id, external_id="newer", config={})

        assert IntegrationManager.github.oauth.find(self.team.id) == self.rows["github_oauth"]
        assert IntegrationManager.github.oauth.list(self.team.id, newest_first=True)[0] == newer

    @parameterized.expand(
        [
            ("every_team", None, {"github_oauth": 2}),
            ("one_team", "other", {"github_oauth": 1}),
        ]
    )
    def test_list_by_external_id(self, _name: str, team_ids: str | None, expected: dict[str, int]) -> None:
        rows = IntegrationManager.github.oauth.list_by_external_id(
            "github_oauth", team_ids=[self.other_team.id] if team_ids else None
        )

        assert {"github_oauth": len(rows)} == expected
        assert all(row.integration_id == "github_oauth" for row in rows)

    @parameterized.expand(
        [
            ("default_auth_type_stores_nothing", lambda: IntegrationManager.github.oauth, {}),
            ("non_default_auth_type_is_stored", lambda: IntegrationManager.github.token, {"auth_type": "token"}),
            (
                "token_on_a_credentials_kind",
                lambda: IntegrationManager.databricks.token,
                {"auth_type": "token"},
            ),
            ("credentials_default", lambda: IntegrationManager.databricks.credentials, {}),
            ("source_kind_default", lambda: IntegrationManager.source("ably").token, {MARKER: "Ably"}),
            (
                "source_row_of_a_catalogue_kind",
                lambda: IntegrationManager.source("stripe").token,
                {MARKER: "Stripe", "auth_type": "token"},
            ),
        ]
    )
    def test_create_stores_the_auth_type_only_when_it_is_not_the_default(
        self, _name: str, accessor: Callable[[], Any], expected_config: dict[str, Any]
    ) -> None:
        config = {MARKER: expected_config[MARKER]} if MARKER in expected_config else {}

        row = accessor().create(
            self.team.id, external_id="new", config=config, sensitive_config={"secret": "s"}, created_by_id=self.user.id
        )

        stored = Integration._base_manager.get(id=row.id)
        assert (stored.config, stored.sensitive_config, stored.created_by_id) == (
            expected_config,
            {"secret": "s"},
            self.user.id,
        )
        assert accessor().get(self.team.id, row.id) == row

    @parameterized.expand(
        [
            ("auth_type_in_config", lambda: IntegrationManager.github.token, {"auth_type": "token"}, ValueError),
            ("marker_through_named_accessor", lambda: IntegrationManager.stripe.token, {MARKER: "Stripe"}, ValueError),
            ("source_row_without_marker", lambda: IntegrationManager.source("ably").token, {}, ValueError),
            (
                "auth_type_the_kind_does_not_support",
                lambda: IntegrationManager.source("postgresql").token,
                {MARKER: "Postgres"},
                UnsupportedAuthType,
            ),
        ]
    )
    def test_create_rejects(
        self, _name: str, accessor: Callable[[], Any], config: dict[str, Any], error: type[Exception]
    ) -> None:
        with self.assertRaises(error):
            accessor().create(self.team.id, external_id="new", config=config)

    def test_upsert_creates_then_replaces_the_config(self) -> None:
        row, created = IntegrationManager.github.token.upsert(self.team.id, "new", config={"a": 1})
        again, created_again = IntegrationManager.github.token.upsert(
            self.team.id, "new", config={"b": 2}, sensitive_config={"token": "t"}, created_by_id=self.user.id
        )

        again.refresh_from_db()
        assert (created, created_again, again.id) == (True, False, row.id)
        assert (again.config, again.sensitive_config, again.created_by_id) == (
            {"b": 2, "auth_type": "token"},
            {"token": "t"},
            self.user.id,
        )

    @parameterized.expand(
        [
            ("other_auth_type", lambda: IntegrationManager.github.token, "github_oauth", {}),
            ("source_row", lambda: IntegrationManager.stripe.token, "stripe_source", {}),
            (
                "named_row_through_source",
                lambda: IntegrationManager.source("stripe").token,
                "stripe_token",
                {MARKER: "Stripe"},
            ),
        ]
    )
    def test_upsert_raises_on_a_row_out_of_scope(
        self, _name: str, accessor: Callable[[], Any], external_id: str, config: dict[str, Any]
    ) -> None:
        before = Integration._base_manager.get(id=self.rows[external_id].id).config

        with self.assertRaises(IntegrationConflict):
            accessor().upsert(self.team.id, external_id, config=config)

        assert Integration._base_manager.get(id=self.rows[external_id].id).config == before

    def test_update_merges_and_removes_keys(self) -> None:
        row = self.rows["github_token"]

        IntegrationManager.github.token.update(
            self.team.id,
            row.id,
            config_patch={"login": "octocat"},
            config_remove=["account", "missing"],
            sensitive_config_patch={"token": "t"},
            errors="TOKEN_REFRESH_FAILED",
        )

        stored = Integration._base_manager.get(id=row.id)
        assert (stored.config, stored.sensitive_config, stored.errors) == (
            {"auth_type": "token", "login": "octocat"},
            {"token": "t"},
            "TOKEN_REFRESH_FAILED",
        )

    @parameterized.expand(
        [
            ("patch_auth_type", {"config_patch": {"auth_type": "oauth"}}, ValueError),
            ("remove_auth_type", {"config_remove": ["auth_type"]}, ValueError),
            ("patch_marker", {"config_patch": {MARKER: "Stripe"}}, ValueError),
        ]
    )
    def test_update_rejects_reserved_keys(self, _name: str, kwargs: dict[str, Any], error: type[Exception]) -> None:
        with self.assertRaises(error):
            IntegrationManager.github.token.update(self.team.id, self.rows["github_token"].id, **kwargs)

    def test_update_raises_for_a_row_out_of_scope(self) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.update(self.team.id, self.rows["github_token"].id, errors="")

    def test_update_atomically_passes_the_locked_row(self) -> None:
        row = self.rows["github_oauth"]
        seen: list[Integration] = []

        def change(current: Integration) -> IntegrationPatch:
            seen.append(current)
            return IntegrationPatch(config_patch={"count": current.config.get("count", 0) + 1})

        IntegrationManager.github.oauth.update_atomically(self.team.id, row.id, change)
        updated = IntegrationManager.github.oauth.update_atomically(self.team.id, row.id, change)

        assert [current.id for current in seen] == [row.id, row.id]
        assert updated.config["count"] == 2

    def test_update_by_external_id_reaches_every_team(self) -> None:
        count = IntegrationManager.github.oauth.update_by_external_id(
            "github_oauth", IntegrationPatch(config_patch={"suspended": True})
        )

        assert count == 2
        assert {
            row.config.get("suspended") for row in Integration._base_manager.filter(integration_id="github_oauth")
        } == {True}
        assert "suspended" not in Integration._base_manager.get(id=self.rows["github_token"].id).config

    def test_delete_checks_usages(self) -> None:
        row = self.rows["github_oauth"]

        def provider(team_id: int, integration_id: int) -> list[IntegrationUsage]:
            return [IntegrationUsage(type="workflow", id="1", name="Flow")] if integration_id == row.id else []

        with _usage_providers(provider):
            with self.assertRaises(IntegrationInUse) as raised:
                IntegrationManager.github.oauth.delete(self.team.id, row.id)
            assert raised.exception.usages == [IntegrationUsage(type="workflow", id="1", name="Flow")]

            IntegrationManager.github.oauth.delete(self.team.id, row.id, ignore_usages=True)
            IntegrationManager.github.token.delete(self.team.id, self.rows["github_token"].id)

        assert not Integration._base_manager.filter(id__in=[row.id, self.rows["github_token"].id]).exists()

    def test_delete_raises_for_a_row_out_of_scope(self) -> None:
        with _usage_providers(), self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.delete(self.team.id, self.rows["github_token"].id)

    def test_delete_by_external_id_reaches_every_team(self) -> None:
        assert IntegrationManager.github.oauth.delete_by_external_id("github_oauth") == 2
        assert Integration._base_manager.filter(id=self.rows["github_token"].id).exists()

    def test_usages_reads_registered_and_product_providers_in_order(self) -> None:
        row = self.rows["postgres"]
        product_module = SimpleNamespace(
            integration_usages=lambda team_id, integration_id: [
                IntegrationUsage(type="warehouse_source", id="2", name="b"),
                IntegrationUsage(type="warehouse_source", id="1", name="a"),
            ]
        )

        with (
            patch.object(usages, "_registered", []),
            patch.object(usages, "_product_providers", None),
            patch.object(usages, "load_product_modules", return_value=iter([product_module])) as load,
        ):
            register_usage_provider(
                lambda team_id, integration_id: [IntegrationUsage(type="batch_export", id="9", name="z")]
            )
            first = IntegrationManager.postgresql.credentials.usages(self.team.id, row.id)
            IntegrationManager.postgresql.credentials.usages(self.team.id, row.id)

        assert [(usage.type, usage.name) for usage in first] == [
            ("batch_export", "z"),
            ("warehouse_source", "a"),
            ("warehouse_source", "b"),
        ]
        load.assert_called_once_with("integration_usages")

    def test_async_forms_match_the_sync_forms(self) -> None:
        row = self.rows["github_oauth"]

        assert async_to_sync(IntegrationManager.github.oauth.aget)(self.team.id, row.id) == row
        assert self._names(async_to_sync(IntegrationManager.github.any.alist)(self.team.id)) == {
            "github_oauth",
            "github_token",
        }
        assert async_to_sync(IntegrationManager.github.token.aexists)(self.team.id) is True
        updated = async_to_sync(IntegrationManager.github.oauth.aupdate)(self.team.id, row.id, config_patch={"x": 1})
        assert updated.config["x"] == 1


class TestRegistration(BaseTest):
    @parameterized.expand(
        [
            ("unknown_source_kind", lambda: IntegrationManager.source("acme-crm-unregistered")),
            ("unknown_kind", lambda: IntegrationManager.kinds("github", "acme-crm")),
            ("no_kinds", lambda: IntegrationManager.kinds()),
        ]
    )
    def test_unknown_kinds_raise(self, _name: str, build: Callable[[], Any]) -> None:
        with self.assertRaises(UnknownIntegrationKind):
            build()

    def test_register_source_kinds_sets_the_default_of_a_new_kind_only(self) -> None:
        register_source_kinds({"acme-sdk-test": AuthType.TOKEN, "stripe": AuthType.CREDENTIALS})

        assert default_auth_type("acme-sdk-test") == AuthType.TOKEN
        assert default_auth_type("stripe") == AuthType.OAUTH
        assert IntegrationManager.source("acme-sdk-test").token.list(self.team.id) == []

    def test_register_source_kinds_rejects_a_changed_default(self) -> None:
        register_source_kinds({"acme-sdk-test-2": AuthType.TOKEN})

        with self.assertRaises(ValueError):
            register_source_kinds({"acme-sdk-test-2": AuthType.CREDENTIALS})

    def test_warehouse_sources_register_their_kinds_at_startup(self) -> None:
        assert IntegrationManager.source("ably").token is not None
        assert default_auth_type("ably") == AuthType.TOKEN
