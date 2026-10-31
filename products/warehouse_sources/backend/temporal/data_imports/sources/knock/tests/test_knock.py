from datetime import datetime
from typing import Any, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knock import KnockSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock import (
    NO_AUDIENCE_KEYS_ERROR,
    NO_OBJECT_COLLECTIONS_ERROR,
    KnockResumeConfig,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS_CONFIG
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource


def _page(endpoint: str, rows: list[dict[str, Any]], after: str | None) -> ScriptedResponse:
    selector = ENDPOINTS_CONFIG[endpoint].data_selector
    return ScriptedResponse(json={selector: rows, "page_info": {"after": after, "before": None, "page_size": 50}})


class TestGetResource:
    @parameterized.expand(
        [
            ("messages", "inserted_at[gte]"),
            ("workflow_recipient_runs", "starting_at"),
        ]
    )
    def test_incremental_uses_endpoint_specific_server_filter(self, endpoint: str, expected_param: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert params[expected_param]["type"] == "incremental"
        assert params[expected_param]["cursor_path"] == "inserted_at"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @parameterized.expand([("messages",), ("users",), ("tenants",), ("workflow_recipient_runs",)])
    def test_full_refresh_sends_no_timestamp_filter(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"page_size"}
        assert resource["write_disposition"] == "replace"


class TestKnockSourceTransport:
    @staticmethod
    def _driver(object_collections: str | None = None, audience_keys: str | None = None) -> SourceDriver:
        return SourceDriver(
            KnockSource(),
            KnockSourceConfig(api_key="sk_test", object_collections=object_collections, audience_keys=audience_keys),
        )

    @parameterized.expand(
        [
            # Messages and workflow recipient runs wrap rows in `items`; users and
            # tenants wrap them in `entries` — a swapped selector syncs 0 rows.
            ("messages",),
            ("users",),
        ]
    )
    def test_rows_extracted_from_endpoint_envelope(self, endpoint: str) -> None:
        result = self._driver().run(endpoint, [_page(endpoint, [{"id": "a"}, {"id": "b"}], after=None)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b"]

    def test_fresh_run_pages_on_after_cursor_and_saves_state(self) -> None:
        result = self._driver().run(
            "messages",
            [
                _page("messages", [{"id": "m1"}], after="cursor-1"),
                _page("messages", [{"id": "m2"}], after="cursor-2"),
                _page("messages", [{"id": "m3"}], after=None),
            ],
        )

        assert result.raised is None
        assert result.params("after") == [None, "cursor-1", "cursor-2"]
        # page_size rides along on every request.
        assert result.params("page_size") == ["50"] * 3
        assert [row["id"] for row in result.rows] == ["m1", "m2", "m3"]
        assert result.saved_states == [KnockResumeConfig(after="cursor-1"), KnockResumeConfig(after="cursor-2")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "messages",
            [_page("messages", [{"id": "m9"}], after=None)],
            resume_state=KnockResumeConfig(after="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("after") == ["cursor-resumed"]

    def test_incremental_run_sends_watermark_as_iso8601(self) -> None:
        result = self._driver().run(
            "messages",
            [_page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after=None)],
            incremental_field="inserted_at",
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert result.raised is None
        assert result.requests[0].param("inserted_at[gte]") == "2026-05-01T12:30:00"

    @parameterized.expand(
        [
            ("messages", ["inserted_at"], ["id"]),
            ("workflow_recipient_runs", ["inserted_at"], ["id"]),
            ("users", None, ["id"]),
            ("tenants", None, ["id"]),
            # Child ids are only guaranteed unique per parent, so the parent id joins the key.
            ("message_events", ["inserted_at"], ["message_id", "id"]),
            ("message_delivery_logs", ["inserted_at"], ["message_id", "id"]),
            ("objects", None, ["collection", "id"]),
        ]
    )
    def test_source_response_partitioning_and_sort_mode(
        self, endpoint: str, partition_keys: list[str] | None, primary_keys: list[str]
    ) -> None:
        fanout = ENDPOINTS_CONFIG[endpoint].fanout
        first_page = _page(fanout.parent_name if fanout else endpoint, [], after=None)
        result = self._driver(object_collections="accounts").run(endpoint, [first_page])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == primary_keys
        # Knock lists return newest-first, so the pipeline must not checkpoint the
        # watermark per batch.
        assert result.response.sort_mode == "desc"
        assert result.response.partition_keys == partition_keys
        assert result.response.partition_mode == ("datetime" if partition_keys else None)

    @parameterized.expand(
        [
            ("message_events", "events"),
            ("message_delivery_logs", "delivery_logs"),
            ("message_activities", "activities"),
        ]
    )
    def test_message_fanout_windows_parent_walk_and_tags_child_rows(self, endpoint: str, child_path: str) -> None:
        result = self._driver().run(
            endpoint,
            [
                _page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after="cursor-1"),
                ScriptedResponse(
                    json={"items": [{"id": "e1", "inserted_at": "2026-06-01T00:00:05Z"}], "page_info": {}}
                ),
                _page("messages", [{"id": "m2", "inserted_at": "2026-06-02T00:00:00Z"}], after=None),
                ScriptedResponse(
                    json={"items": [{"id": "e1", "inserted_at": "2026-06-02T00:00:05Z"}], "page_info": {}}
                ),
            ],
            incremental_field="message_inserted_at",
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/messages",
            f"/v1/messages/m1/{child_path}",
            "/v1/messages",
            f"/v1/messages/m2/{child_path}",
        ]
        # The child endpoints take no timestamp filter, so the watermark bounds the parent walk.
        assert result.requests[0].param("inserted_at[gte]") == "2026-05-01T12:30:00"
        assert result.requests[2].param("after") == "cursor-1"
        assert all(request.param("inserted_at[gte]") is None for request in result.requests[1::2])
        assert [(r["message_id"], r["id"], r["message_inserted_at"]) for r in result.rows] == [
            ("m1", "e1", "2026-06-01T00:00:00Z"),
            ("m2", "e1", "2026-06-02T00:00:00Z"),
        ]

    def test_message_fanout_full_refresh_walks_every_message(self) -> None:
        result = self._driver().run(
            "message_events",
            [
                _page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after=None),
                ScriptedResponse(json={"items": [{"id": "e1"}], "page_info": {}}),
            ],
        )

        assert result.raised is None
        assert set(result.requests[0].query) == {"page_size"}

    def test_schedules_fan_out_over_percent_encoded_user_ids(self) -> None:
        result = self._driver().run(
            "schedules",
            [
                _page("users", [{"id": "team/jane"}], after=None),
                ScriptedResponse(json={"entries": [{"id": "s1"}], "page_info": {}}),
            ],
        )

        assert result.raised is None
        assert result.paths[1] == "/v1/users/team%2Fjane/schedules"
        assert [row["id"] for row in result.rows] == ["s1"]

    @parameterized.expand(
        [
            (
                "user_subscriptions",
                "/v1/users/team%2Fjane/subscriptions",
                ScriptedResponse(
                    json={
                        "entries": [
                            {
                                "object": {"collection": "accounts", "id": "acct_1"},
                                "recipient": {"id": "team/jane"},
                                "inserted_at": "2026-06-01T00:00:00Z",
                            }
                        ],
                        "page_info": {"after": None},
                    }
                ),
                "50",
                {"user_id": "team/jane", "object_collection": "accounts", "object_id": "acct_1"},
            ),
            # Preferences come back as a bare array with no pagination params documented.
            (
                "user_preferences",
                "/v1/users/team%2Fjane/preferences",
                ScriptedResponse(json=[{"id": "default", "channel_types": {"email": True}}]),
                None,
                {"user_id": "team/jane", "id": "default"},
            ),
        ]
    )
    def test_user_fanout_tags_rows_with_decoded_user_id(
        self,
        endpoint: str,
        child_path: str,
        child_response: ScriptedResponse,
        page_size: str | None,
        expected: dict[str, Any],
    ) -> None:
        result = self._driver().run(endpoint, [_page("users", [{"id": "team/jane"}], after=None), child_response])

        assert result.raised is None
        assert result.paths == ["/v1/users", child_path]
        assert [request.param("page_size") for request in result.requests] == [page_size, page_size]
        assert len(result.rows) == 1
        assert {key: result.rows[0].get(key) for key in expected} == expected

    def test_audience_members_walk_each_configured_audience(self) -> None:
        result = self._driver(audience_keys="beta, vip/1").run(
            "audience_members",
            [
                _page("audience_members", [{"user_id": "u1", "tenant": None}], after="cursor-1"),
                _page("audience_members", [{"user_id": "u2", "tenant": "t1"}], after=None),
                _page("audience_members", [{"user_id": "u1", "tenant": None}], after=None),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/audiences/beta/members"] * 2 + ["/v1/audiences/vip%2F1/members"]
        assert result.params("after") == [None, "cursor-1", None]
        assert result.params("page_size") == [None] * 3
        assert [(row["audience_key"], row["user_id"]) for row in result.rows] == [
            ("beta", "u1"),
            ("beta", "u2"),
            ("vip/1", "u1"),
        ]

    def test_audience_members_fails_when_knock_ignores_the_cursor(self) -> None:
        result = self._driver(audience_keys="beta").run(
            "audience_members",
            [
                _page("audience_members", [{"user_id": "u1"}], after="cursor-1"),
                _page("audience_members", [{"user_id": "u1"}], after="cursor-1"),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 2

    def test_objects_walk_each_configured_collection(self) -> None:
        result = self._driver(object_collections=" accounts, projects,accounts ").run(
            "objects",
            [
                _page("objects", [{"id": "a1", "collection": "accounts"}], after="cursor-1"),
                _page("objects", [{"id": "a2", "collection": "accounts"}], after=None),
                _page("objects", [{"id": "p1", "collection": "projects"}], after=None),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/objects/accounts"] * 2 + ["/v1/objects/projects"]
        assert result.params("after") == [None, "cursor-1", None]
        assert [row["id"] for row in result.rows] == ["a1", "a2", "p1"]
        assert result.saved_states == [
            KnockResumeConfig(collection="accounts"),
            KnockResumeConfig(after="cursor-1", collection="accounts"),
            KnockResumeConfig(collection="projects"),
        ]

    def test_objects_resume_skips_finished_collections(self) -> None:
        result = self._driver(object_collections="accounts,projects").run(
            "objects",
            [_page("objects", [{"id": "p8", "collection": "projects"}], after=None)],
            resume_state=KnockResumeConfig(after="cursor-7", collection="projects"),
        )

        assert result.raised is None
        assert result.paths == ["/v1/objects/projects"]
        assert result.requests[0].param("after") == "cursor-7"

    @parameterized.expand(
        [
            ("objects", None, NO_OBJECT_COLLECTIONS_ERROR),
            ("objects", "", NO_OBJECT_COLLECTIONS_ERROR),
            ("objects", " , ", NO_OBJECT_COLLECTIONS_ERROR),
            ("audience_members", None, NO_AUDIENCE_KEYS_ERROR),
            ("audience_members", " , ", NO_AUDIENCE_KEYS_ERROR),
        ]
    )
    def test_keyed_table_without_keys_fails_with_actionable_error(
        self, endpoint: str, keys: str | None, expected_error: str
    ) -> None:
        # Each table reads its own field, so the other field's keys must not stand in for it.
        driver = (
            self._driver(object_collections=keys, audience_keys="beta")
            if endpoint == "objects"
            else self._driver(object_collections="accounts", audience_keys=keys)
        )
        result = driver.run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == expected_error


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {}, (True, None)),
        ]
    )
    def test_status_mapping(
        self, _name: str, status_code: int, body: dict[str, Any], expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=body))) as network:
            assert validate_credentials("sk_test") == expected
        assert network.requests_log[0].path == "/v1/users"
        assert network.requests_log[0].param("page_size") == "1"
