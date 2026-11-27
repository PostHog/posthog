import copy
from typing import Any, cast

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (
    OAuthPointer,
    OAuthPointerShapeError,
    declared_oauth_pointer_paths,
    find_in_use_oauth_pointer,
    with_pointer_at,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

T = ExternalDataSourceType

# A switch group with an OAuth field. No released source has one, but the walk must read it.
_SWITCH_GROUP_FIELDS = cast(
    list[FieldType],
    [
        SourceFieldSwitchGroupConfig(
            name="use_app",
            label="Use an app",
            default=False,
            fields=cast(
                list[FieldType],
                [SourceFieldOauthConfig(name="app_integration_id", label="App", kind="github", required=True)],
            ),
        ),
        SourceFieldInputConfig(
            name="token",
            label="Token",
            type=SourceFieldInputConfigType.PASSWORD,
            required=False,
            placeholder="",
            secret=True,
        ),
    ],
)


class TestInUseOAuthPointer(SimpleTestCase):
    @parameterized.expand(
        [
            ("top_level_int", T.HUBSPOT, {"hubspot_integration_id": 7}, ("hubspot_integration_id",), 7),
            ("top_level_string", T.HUBSPOT, {"hubspot_integration_id": "7"}, ("hubspot_integration_id",), 7),
            ("top_level_padded_string", T.HUBSPOT, {"hubspot_integration_id": " 7 "}, ("hubspot_integration_id",), 7),
            (
                "short_key_name",
                T.REDDITADS,
                {"reddit_integration_id": "7", "account_id": "a"},
                ("reddit_integration_id",),
                7,
            ),
            (
                "oauth_next_to_typed_in_select",
                T.PARDOT,
                {"pardot_integration_id": 7, "environment": "sandbox"},
                ("pardot_integration_id",),
                7,
            ),
            ("missing", T.HUBSPOT, {}, None, None),
            ("none", T.HUBSPOT, {"hubspot_integration_id": None}, None, None),
            ("blank", T.HUBSPOT, {"hubspot_integration_id": ""}, None, None),
            (
                "nested_selected",
                T.GITHUB,
                {"auth_method": {"selection": "oauth", "github_integration_id": "7", "personal_access_token": ""}},
                ("auth_method", "github_integration_id"),
                7,
            ),
            (
                "nested_unselected_stale",
                T.GITHUB,
                {"auth_method": {"selection": "pat", "github_integration_id": "7", "personal_access_token": "fake"}},
                None,
                None,
            ),
            (
                "stripe_selected",
                T.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": 7}},
                ("auth_method", "stripe_integration_id"),
                7,
            ),
            (
                "stripe_unselected_stale",
                T.STRIPE,
                {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake", "stripe_integration_id": 7}},
                None,
                None,
            ),
            (
                "resend_selected",
                T.RESEND,
                {"auth_method": {"selection": "oauth", "resend_integration_id": "7"}},
                ("auth_method", "resend_integration_id"),
                7,
            ),
            (
                "apple_selected",
                T.APPLESEARCHADS,
                {"auth_method": {"selection": "oauth", "apple_ads_integration_id": "7"}},
                ("auth_method", "apple_ads_integration_id"),
                7,
            ),
            (
                "bigquery_service_account",
                T.BIGQUERY,
                {"auth_type": {"selection": "service_account", "google_cloud_service_account_integration_id": "7"}},
                ("auth_type", "google_cloud_service_account_integration_id"),
                7,
            ),
            (
                "bigquery_key_file_stale",
                T.BIGQUERY,
                {"auth_type": {"selection": "key_file", "google_cloud_service_account_integration_id": "7"}},
                None,
                None,
            ),
            ("nested_select_absent", T.GITHUB, {"repository": "posthog/posthog"}, None, None),
            ("slack_hidden_legacy_key", T.SLACK, {"slack_integration_id": "7"}, ("slack_integration_id",), 7),
            (
                "slack_token_wins",
                T.SLACK,
                {"slack_integration_id": "7", "slack_access_token": "fake-token"},
                None,
                None,
            ),
            ("slack_bring_your_own", T.SLACK, {"slack_access_token": "fake-token"}, None, None),
            ("typed_in_only", T.POSTGRES, {"host": "db.example.com", "password": "fake"}, None, None),
        ]
    )
    def test_finds_the_pointer_the_sync_uses(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        inputs: dict[str, Any],
        path: tuple[str, ...] | None,
        integration_id: int | None,
    ) -> None:
        pointer = SourceRegistry.get_source(source_type).in_use_oauth_pointer(inputs)

        assert pointer == (None if path is None else OAuthPointer(path=path, integration_id=cast(int, integration_id)))

    @parameterized.expand(
        [
            ("select_as_bare_string", T.GITHUB, {"auth_method": "oauth", "github_integration_id": "7"}),
            ("flat_legacy_pointer", T.STRIPE, {"stripe_integration_id": "7"}),
            ("unknown_selection", T.GITHUB, {"auth_method": {"selection": "app", "github_integration_id": "7"}}),
            ("no_selection", T.GITHUB, {"auth_method": {"github_integration_id": "7"}}),
            ("not_a_number", T.HUBSPOT, {"hubspot_integration_id": "abc"}),
            ("bool", T.HUBSPOT, {"hubspot_integration_id": True}),
            ("negative", T.HUBSPOT, {"hubspot_integration_id": "-7"}),
            ("slack_not_a_number", T.SLACK, {"slack_integration_id": "abc"}),
        ]
    )
    def test_refuses_a_shape_it_cannot_read(
        self, _name: str, source_type: ExternalDataSourceType, inputs: dict[str, Any]
    ) -> None:
        with self.assertRaises(OAuthPointerShapeError):
            SourceRegistry.get_source(source_type).in_use_oauth_pointer(inputs)

    @parameterized.expand(
        [
            (
                "on",
                {"use_app": {"enabled": True, "app_integration_id": "7"}},
                OAuthPointer(path=("use_app", "app_integration_id"), integration_id=7),
            ),
            (
                "on_as_string",
                {"use_app": {"enabled": "true", "app_integration_id": 7}},
                OAuthPointer(path=("use_app", "app_integration_id"), integration_id=7),
            ),
            ("off_stale", {"use_app": {"enabled": False, "app_integration_id": "7"}}, None),
            ("no_enabled_key", {"use_app": {"app_integration_id": "7"}}, None),
        ]
    )
    def test_reads_a_switch_group(self, _name: str, inputs: dict[str, Any], expected: OAuthPointer | None) -> None:
        assert find_in_use_oauth_pointer(_SWITCH_GROUP_FIELDS, inputs) == expected

    @parameterized.expand(
        [
            ("top_level", T.HUBSPOT, {("hubspot_integration_id",)}),
            ("nested", T.GITHUB, {("auth_method", "github_integration_id")}),
            ("bigquery", T.BIGQUERY, {("auth_type", "google_cloud_service_account_integration_id")}),
            ("slack_hidden", T.SLACK, {("slack_integration_id",)}),
            ("typed_in_only", T.POSTGRES, set()),
        ]
    )
    def test_lists_every_pointer_path(
        self, _name: str, source_type: ExternalDataSourceType, expected: set[tuple[str, ...]]
    ) -> None:
        assert SourceRegistry.get_source(source_type).oauth_pointer_paths == expected

    def test_switch_group_paths(self) -> None:
        assert declared_oauth_pointer_paths(_SWITCH_GROUP_FIELDS) == {("use_app", "app_integration_id")}


class TestInUseOAuthSlot(SimpleTestCase):
    @parameterized.expand(
        [
            ("top_level_without_value", T.HUBSPOT, {}, ("hubspot_integration_id",)),
            (
                "nested_selected_without_value",
                T.GITHUB,
                {"auth_method": {"selection": "oauth"}},
                ("auth_method", "github_integration_id"),
            ),
            (
                "nested_typed_in_selected",
                T.GITHUB,
                {"auth_method": {"selection": "pat", "personal_access_token": "fake"}},
                None,
            ),
            (
                "bigquery_service_account",
                T.BIGQUERY,
                {"auth_type": {"selection": "service_account"}},
                ("auth_type", "google_cloud_service_account_integration_id"),
            ),
            ("slack_without_token", T.SLACK, {}, ("slack_integration_id",)),
            ("slack_with_token", T.SLACK, {"slack_access_token": "fake-token"}, None),
            ("typed_in_only", T.POSTGRES, {"host": "db.example.com"}, None),
        ]
    )
    def test_finds_where_the_in_use_pointer_goes(
        self, _name: str, source_type: ExternalDataSourceType, inputs: dict[str, Any], expected: tuple[str, ...] | None
    ) -> None:
        assert SourceRegistry.get_source(source_type).in_use_oauth_slot(inputs) == expected

    @parameterized.expand(
        [
            ("top_level_set", {"a": 1}, ("hubspot_integration_id",), 7, {"a": 1, "hubspot_integration_id": 7}),
            ("top_level_removed", {"a": 1, "hubspot_integration_id": "7"}, ("hubspot_integration_id",), None, {"a": 1}),
            (
                "nested_set",
                {"auth_method": {"selection": "oauth"}},
                ("auth_method", "github_integration_id"),
                7,
                {"auth_method": {"selection": "oauth", "github_integration_id": 7}},
            ),
            (
                "nested_removed",
                {"auth_method": {"selection": "oauth", "github_integration_id": "7"}},
                ("auth_method", "github_integration_id"),
                None,
                {"auth_method": {"selection": "oauth"}},
            ),
        ]
    )
    def test_with_pointer_at_copies_the_inputs(
        self,
        _name: str,
        inputs: dict[str, Any],
        path: tuple[str, ...],
        integration_id: int | None,
        expected: dict[str, Any],
    ) -> None:
        before = copy.deepcopy(inputs)

        assert with_pointer_at(inputs, path, integration_id) == expected
        assert inputs == before

    def test_with_pointer_at_refuses_a_group_that_is_not_a_mapping(self) -> None:
        with self.assertRaises(OAuthPointerShapeError):
            with_pointer_at({"auth_method": "oauth"}, ("auth_method", "github_integration_id"), 7)
