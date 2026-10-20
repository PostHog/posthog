from datetime import UTC, datetime
from typing import Any, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.courier import (
    CourierResumeConfig,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import (
    ENDPOINTS_CONFIG,
    FANOUT_ENDPOINT_CONFIGS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.source import CourierSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.courier import (
    CourierSourceConfig,
)


def _page(endpoint: str, rows: list[dict[str, Any]], cursor: str | None) -> ScriptedResponse:
    """Build a page response using this endpoint's real envelope shape.

    Every endpoint but Tenants nests the cursor under `paging`; Tenants returns it at the
    response's top level.
    """
    config = FANOUT_ENDPOINT_CONFIGS[endpoint]
    body: dict[str, Any] = {config.data_selector: rows}
    if config.cursor_path == "cursor":
        body["cursor"] = cursor
        body["has_more"] = cursor is not None
    else:
        body["paging"] = {"more": cursor is not None, "cursor": cursor}
    return ScriptedResponse(json=body)


def _versions_page(rows: list[dict[str, Any]], cursor: str | None) -> ScriptedResponse:
    """Build a journey-versions response, whose cursor nests under `paging`.

    The endpoint's parent listing carries its cursor at the response's top level instead, so
    `_page` builds the wrong shape for this one.
    """
    return ScriptedResponse(json={"results": rows, "paging": {"more": cursor is not None, "cursor": cursor}})


def _preferences_page(schedules: list[dict[str, Any]] | None) -> ScriptedResponse:
    """Build a `/preferences/sections` response with `schedules` nested where Courier puts them.

    `None` is a workspace whose topics have no digest configured at all.
    """
    topic: dict[str, Any] = {"id": "pt_1", "name": "Product updates"}
    if schedules is not None:
        topic["digest"] = {"schedules": schedules}
    return ScriptedResponse(json={"results": [{"id": "ps_1", "topics": [topic]}]})


def _driver() -> SourceDriver:
    return SourceDriver(CourierSource(), CourierSourceConfig(api_key="sk_test"))


def _drive(endpoint: str, responses: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    result = _driver().run(endpoint, responses, **inputs)
    assert result.raised is None
    return result


class TestGetResource:
    def test_incremental_uses_enqueued_after_filter(self) -> None:
        resource = get_resource("Messages", should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert params["enqueued_after"]["type"] == "incremental"
        assert params["enqueued_after"]["cursor_path"] == "enqueued"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @parameterized.expand(
        [
            ("Messages",),
            ("AuditEvents",),
            ("Audiences",),
            ("Brands",),
            ("Lists",),
            ("NotificationTemplates",),
            ("Tenants",),
            ("Journeys",),
            ("Automations",),
            ("PreferenceChanges",),
        ]
    )
    def test_full_refresh_sends_no_timestamp_filter(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"limit"}
        assert resource["write_disposition"] == "replace"

    @parameterized.expand(
        [
            ("AuditEvents",),
            ("Audiences",),
            ("Brands",),
            ("Lists",),
            ("NotificationTemplates",),
            ("Tenants",),
            ("Journeys",),
            ("Automations",),
        ]
    )
    def test_endpoints_without_a_server_filter_ignore_incremental_flag(self, endpoint: str) -> None:
        # These endpoints have no documented server-side timestamp filter, so even if asked for
        # an incremental run there is no filter param to add.
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"limit"}


class TestCourierSourceTransport:
    @parameterized.expand(
        [
            ("Messages",),
            ("AuditEvents",),
            ("Audiences",),
            ("Brands",),
            ("Lists",),
            ("NotificationTemplates",),
            ("Tenants",),
            ("Journeys",),
            ("Automations",),
            ("PreferenceSections",),
            ("PreferenceChanges",),
        ]
    )
    def test_rows_extracted_from_endpoint_envelope(self, endpoint: str) -> None:
        # A swapped `data_selector` ("results" vs "items", or the wrong top-level cursor key for
        # Tenants) silently syncs 0 rows instead of raising, so this locks the real shape in.
        result = _drive(endpoint, [_page(endpoint, [{"id": "a"}, {"id": "b"}], cursor=None)])

        assert [row["id"] for row in result.rows] == ["a", "b"]

    def test_fresh_run_pages_on_cursor_and_saves_state(self) -> None:
        responses = [
            _page("Messages", [{"id": "m1"}], cursor="cursor-1"),
            _page("Messages", [{"id": "m2"}], cursor="cursor-2"),
            _page("Messages", [{"id": "m3"}], cursor=None),
        ]
        result = _drive("Messages", responses)

        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.params("limit") == ["100", "100", "100"]
        assert [row["id"] for row in result.rows] == ["m1", "m2", "m3"]

        assert result.saved_states == [CourierResumeConfig(cursor="cursor-1"), CourierResumeConfig(cursor="cursor-2")]

    @parameterized.expand([("Tenants",), ("Journeys",), ("Automations",)])
    def test_pages_on_top_level_cursor(self, endpoint: str) -> None:
        # These endpoints return their cursor at the response's top level rather than nested
        # under `paging`, so a regression here silently disables pagination.
        responses = [
            _page(endpoint, [{"id": "r1"}], cursor="cursor-1"),
            _page(endpoint, [{"id": "r2"}], cursor=None),
        ]
        result = _drive(endpoint, responses)

        assert result.params("cursor") == [None, "cursor-1"]
        assert [row["id"] for row in result.rows] == ["r1", "r2"]

    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        # The preference sections listing documents no params at all, so the page size every
        # other endpoint gets must not be sent to it.
        result = _drive("PreferenceSections", [_page("PreferenceSections", [{"id": "ps_1"}], cursor=None)])

        assert result.paths == ["/preferences/sections"]
        assert result.queries == [{}]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        responses = [_page("Messages", [{"id": "m9"}], cursor=None)]
        result = _drive("Messages", responses, resume_state=CourierResumeConfig(cursor="cursor-resumed"))

        assert result.params("cursor") == ["cursor-resumed"]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        result = _drive("Messages", [_page("Messages", [{"id": "only"}], cursor=None)])

        assert result.saved_states == []

    @parameterized.expand(
        [
            ("messages", "Messages", "enqueued_after", datetime(2026, 5, 1, 12, 30), "2026-05-01T12:30:00"),
            ("preference_changes", "PreferenceChanges", "since", datetime(2026, 5, 1, 12, 30), "2026-05-01T12:30:00"),
            # No prior watermark (first incremental sync): must fall back to a real ISO-8601
            # value, not stringify `None` into the literal "since=None".
            ("messages_first_sync", "Messages", "enqueued_after", None, "1970-01-01T00:00:00Z"),
            ("preference_changes_first_sync", "PreferenceChanges", "since", None, "1970-01-01T00:00:00Z"),
        ]
    )
    def test_incremental_run_sends_watermark_as_iso8601(
        self, _name: str, endpoint: str, param: str, last_value: datetime | None, expected: str
    ) -> None:
        responses = [_page(endpoint, [{"id": "r1"}], cursor=None)]
        result = _drive(
            endpoint,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.params(param) == [expected]

    def test_epoch_millis_fields_are_converted_to_datetime(self) -> None:
        # `enqueued`/`sent`/etc. arrive as epoch-millisecond ints; left unconverted, the
        # partitioner would misread them as epoch seconds and bucket everything into the wrong
        # decade.
        responses = [_page("Messages", [{"id": "m1", "enqueued": 1_700_000_000_000, "sent": None}], cursor=None)]
        result = _drive("Messages", responses)

        assert result.rows[0]["enqueued"] == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC)
        assert result.rows[0]["sent"] is None

    def test_iso_string_fields_are_converted_to_datetime(self) -> None:
        responses = [_page("Audiences", [{"id": "a1", "created_at": "2026-01-15T10:30:00Z"}], cursor=None)]
        result = _drive("Audiences", responses)

        assert result.rows[0]["created_at"] == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

    @parameterized.expand(
        [
            ("Messages", ["enqueued"], "desc"),
            ("AuditEvents", ["timestamp"], "asc"),
            ("Audiences", ["created_at"], "asc"),
            ("Brands", None, "asc"),
            ("Lists", ["created"], "asc"),
            ("NotificationTemplates", None, "asc"),
            ("Tenants", None, "asc"),
            ("Journeys", ["createdAt"], "asc"),
            ("Automations", ["createdAt"], "asc"),
            ("PreferenceSections", ["created"], "asc"),
            ("PreferenceChanges", ["timestamp"], "desc"),
        ]
    )
    def test_source_response_partitioning_and_sort_mode(
        self, endpoint: str, partition_keys: list[str] | None, sort_mode: str
    ) -> None:
        result = _drive(endpoint, [_page(endpoint, [], cursor=None)])
        assert result.response is not None

        assert result.response.primary_keys == list(ENDPOINTS_CONFIG[endpoint].primary_keys)
        assert result.response.sort_mode == sort_mode
        assert result.response.partition_keys == partition_keys
        assert result.response.partition_mode == ("datetime" if partition_keys else None)


class TestCourierFanout:
    """Endpoints reachable only per parent record: the parent listing is walked first."""

    def test_audience_members_are_fetched_per_audience(self) -> None:
        result = _drive(
            "AudienceMembers",
            [
                _page("Audiences", [{"id": "aud-1"}, {"id": "aud-2"}], cursor=None),
                _page("AudienceMembers", [{"audience_id": "aud-1", "member_id": "u1"}], cursor=None),
                _page("AudienceMembers", [{"audience_id": "aud-2", "member_id": "u2"}], cursor=None),
            ],
        )

        assert result.paths == ["/audiences", "/audiences/aud-1/members", "/audiences/aud-2/members"]
        assert [(row["audience_id"], row["member_id"]) for row in result.rows] == [
            ("aud-1", "u1"),
            ("aud-2", "u2"),
        ]

    def test_list_subscriptions_carry_their_list_id(self) -> None:
        # The subscription object has no reference back to its list, so without the projected
        # parent id the primary key collapses to the recipient and rows collide across lists.
        result = _drive(
            "ListSubscriptions",
            [
                _page("Lists", [{"id": "list-a"}], cursor=None),
                _page("ListSubscriptions", [{"recipientId": "u1", "created": "2026-01-15T10:30:00Z"}], cursor=None),
            ],
        )

        assert result.paths == ["/lists", "/lists/list-a/subscriptions"]
        assert result.rows[0]["list_id"] == "list-a"
        assert result.rows[0]["created"] == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_message_history_projects_and_normalizes_the_parent_message(self) -> None:
        result = _drive(
            "MessageHistory",
            [
                _page("Messages", [{"id": "msg-1", "enqueued": 1_700_000_000_000}], cursor=None),
                _page("MessageHistory", [{"type": "SENT", "ts": 1_700_000_001_000}], cursor=None),
            ],
        )

        assert result.paths == ["/messages", "/messages/msg-1/history"]
        assert result.rows[0]["message_id"] == "msg-1"
        # The projected parent timestamp is what the table partitions on and keys its watermark
        # from, so it has to arrive as a datetime rather than raw epoch millis.
        assert result.rows[0]["enqueued"] == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC)
        assert result.rows[0]["ts"] == datetime.fromtimestamp(1_700_000_001_000 / 1000, tz=UTC)

    def test_message_history_incremental_bounds_the_parent_listing(self) -> None:
        # The history endpoint takes no timestamp filter, so an incremental run can only avoid
        # re-fetching every message's history by windowing the parent listing.
        result = _drive(
            "MessageHistory",
            [
                _page("Messages", [{"id": "msg-1", "enqueued": 1_700_000_000_000}], cursor=None),
                _page("MessageHistory", [{"type": "SENT", "ts": 1_700_000_001_000}], cursor=None),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert result.params("enqueued_after") == ["2026-05-01T12:30:00", None]

    def test_message_history_full_refresh_sends_no_watermark(self) -> None:
        result = _drive(
            "MessageHistory",
            [
                _page("Messages", [{"id": "msg-1", "enqueued": 1_700_000_000_000}], cursor=None),
                _page("MessageHistory", [], cursor=None),
            ],
        )

        assert result.params("enqueued_after") == [None, None]

    def test_tenant_users_are_fetched_per_tenant(self) -> None:
        # A user belongs to many tenants, so without the projected parent id the primary key
        # collapses to the user and rows collide across tenants.
        result = _drive(
            "TenantUsers",
            [
                _page("Tenants", [{"id": "tenant-a"}, {"id": "tenant-b"}], cursor=None),
                _page("TenantUsers", [{"user_id": "u1", "type": "user"}], cursor=None),
                _page("TenantUsers", [{"user_id": "u2", "type": "user"}], cursor=None),
            ],
        )

        assert result.paths == ["/tenants", "/tenants/tenant-a/users", "/tenants/tenant-b/users"]
        assert [(row["tenant_id"], row["user_id"]) for row in result.rows] == [
            ("tenant-a", "u1"),
            ("tenant-b", "u2"),
        ]
        assert result.params("limit") == ["100", "100", "100"]

    def test_journey_versions_carry_their_journey_id(self) -> None:
        result = _drive(
            "JourneyVersions",
            [
                _page("Journeys", [{"id": "jry-1", "createdAt": "2026-01-15T10:30:00Z"}], cursor=None),
                _page("JourneyVersions", [{"version": "v2", "created": 1_700_000_000_000}], cursor=None),
            ],
        )

        assert result.paths == ["/journeys", "/journeys/jry-1/versions"]
        assert result.rows[0]["journey_id"] == "jry-1"
        # The table partitions on `created`, which arrives as epoch millis.
        assert result.rows[0]["created"] == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC)

    def test_journey_versions_page_on_their_own_nested_cursor(self) -> None:
        # The parent /journeys walk finds its cursor at the top level, so a child that reused it
        # would stop after one page and drop most of a journey's publish history.
        result = _drive(
            "JourneyVersions",
            [
                _page("Journeys", [{"id": "jry-1"}], cursor=None),
                _versions_page([{"version": "v2"}], cursor="cursor-1"),
                _versions_page([{"version": "v1"}], cursor=None),
            ],
        )

        assert result.paths == ["/journeys", "/journeys/jry-1/versions", "/journeys/jry-1/versions"]
        assert result.params("cursor") == [None, None, "cursor-1"]
        assert [row["version"] for row in result.rows] == ["v2", "v1"]

    def test_journey_versions_stop_when_the_cursor_repeats(self) -> None:
        # Courier documents no cursor param on this endpoint. If it ignores the one we send, the
        # same page and cursor come back forever, so a repeated cursor has to end the walk.
        result = _drive(
            "JourneyVersions",
            [
                _page("Journeys", [{"id": "jry-1"}], cursor=None),
                _versions_page([{"version": "v1"}], cursor="stuck"),
                _versions_page([{"version": "v1"}], cursor="stuck"),
            ],
        )

        assert result.paths == ["/journeys", "/journeys/jry-1/versions", "/journeys/jry-1/versions"]
        assert [row["version"] for row in result.rows] == ["v1", "v1"]

    def test_notification_template_versions_carry_their_template_id_and_page_at_ten(self) -> None:
        # Courier rejects a `limit` above 10 on the versions endpoint, so the child must not
        # inherit the page size of its template listing.
        result = _drive(
            "NotificationTemplateVersions",
            [
                _page("NotificationTemplates", [{"id": "nt_1"}], cursor=None),
                _page("NotificationTemplateVersions", [{"version": "v002", "created": 1_700_000_000_000}], "c-1"),
                _page("NotificationTemplateVersions", [{"version": "v001", "created": 1_690_000_000_000}], None),
            ],
        )

        assert result.paths == ["/notifications", "/notifications/nt_1/versions", "/notifications/nt_1/versions"]
        assert result.params("limit") == ["100", "10", "10"]
        assert result.params("cursor") == [None, None, "c-1"]
        assert [(row["template_id"], row["version"]) for row in result.rows] == [("nt_1", "v002"), ("nt_1", "v001")]
        assert result.rows[0]["created"] == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC)

    def test_preference_topics_are_fetched_per_section_without_params(self) -> None:
        # Neither listing documents a page-size param, and the topic carries no reference back to
        # its section, so the section id has to be projected in from the parent.
        result = _drive(
            "PreferenceTopics",
            [
                _page("PreferenceSections", [{"id": "ps_1"}, {"id": "ps_2"}], cursor=None),
                _page("PreferenceTopics", [{"id": "pt_1", "created": "2026-01-15T10:30:00.000Z"}], cursor=None),
                _page("PreferenceTopics", [{"id": "pt_2"}], cursor=None),
            ],
        )

        assert result.paths == [
            "/preferences/sections",
            "/preferences/sections/ps_1/topics",
            "/preferences/sections/ps_2/topics",
        ]
        assert result.queries == [{}, {}, {}]
        assert [(row["section_id"], row["id"]) for row in result.rows] == [("ps_1", "pt_1"), ("ps_2", "pt_2")]
        assert result.rows[0]["created"] == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_digest_instances_flatten_schedule_ids_out_of_the_preferences_response(self) -> None:
        # Courier exposes no listing of digest schedules, so the ids come from the schedules
        # nested inside each preference topic's digest config.
        result = _drive(
            "DigestInstances",
            [
                _preferences_page([{"schedule_id": "sch_01abc"}, {"schedule_id": "sch_02def"}]),
                _page("DigestInstances", [{"digest_instance_id": "di-1", "user_id": "u1"}], cursor=None),
                _page("DigestInstances", [{"digest_instance_id": "di-2", "user_id": "u2"}], cursor=None),
            ],
        )

        assert result.paths == [
            "/preferences/sections",
            "/digests/schedules/sch_01abc/instances",
            "/digests/schedules/sch_02def/instances",
        ]
        assert [(row["schedule_id"], row["digest_instance_id"]) for row in result.rows] == [
            ("sch_01abc", "di-1"),
            ("sch_02def", "di-2"),
        ]
        # The preferences listing documents no params at all; the child still pages at 100.
        assert result.queries[0] == {}
        assert result.params("limit") == [None, "100", "100"]

    def test_digest_instances_percent_encode_a_legacy_schedule_id(self) -> None:
        # Schedule ids created before the `sch_...` format contain a literal "/", which would
        # otherwise be spliced into the path unescaped and 404.
        result = _drive(
            "DigestInstances",
            [
                _preferences_page([{"schedule_id": "sch/00000000-0000-0000-0000-000000000000"}]),
                _page(
                    "DigestInstances",
                    [{"digest_instance_id": "di-1", "created_at": "2026-01-15T10:30:00Z"}],
                    cursor=None,
                ),
            ],
        )

        assert result.paths == [
            "/preferences/sections",
            "/digests/schedules/sch%2F00000000-0000-0000-0000-000000000000/instances",
        ]
        assert result.rows[0]["schedule_id"] == "sch/00000000-0000-0000-0000-000000000000"
        assert result.rows[0]["created_at"] == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_digest_instances_sync_nothing_when_no_digest_is_configured(self) -> None:
        # A workspace with no digests has no `digest` key to match, which is a legitimate empty
        # result rather than the envelope change a required selector fails the sync over.
        result = _drive("DigestInstances", [_preferences_page(None)])

        assert result.paths == ["/preferences/sections"]
        assert result.rows == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, (True, None)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials("sk_test") == expected
        assert {request.path for request in network.requests_log} == {"/messages"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}

    def test_network_error_is_false(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            ok, message = validate_credentials("sk_test")
            assert ok is False
        assert {request.path for request in network.requests_log} == {"/messages"}
