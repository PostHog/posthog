from typing import Any

import pytest

from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably import (
    ABLY_VERSION_2,
    AblyResumeConfig,
    _add_channel_path,
    _add_interval_start,
    _add_message_time,
    _parse_interval_start,
    get_resource,
    split_api_key,
    validate_credentials,
    version_header,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ably.source import AblySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ably import AblySourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(AblySource(), AblySourceConfig(api_key="app.key:secret", unit="hour"))


def _page(body: list[dict[str, Any]], *, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json=body, headers=headers)


class TestVersionHeader:
    @pytest.mark.parametrize(
        ("api_version", "expected"),
        [
            # "2" pins the source to protocol 2 explicitly. The legacy unversioned label sends no
            # header — Ably protocol 1 is sunset, so `X-Ably-Version: 1` would only fail; the empty
            # header keeps those rows on Ably's current default until the repin migration moves them.
            (ABLY_VERSION_2, {"X-Ably-Version": "2"}),
            (UNVERSIONED_API_VERSION, {}),
        ],
    )
    def test_maps_version_to_header(self, api_version: str, expected: dict[str, str]) -> None:
        assert version_header(api_version) == expected


class TestSplitApiKey:
    @pytest.mark.parametrize(
        ("api_key", "expected_username", "expected_password"),
        [
            ("app123.key456:secretvalue", "app123.key456", "secretvalue"),
            # A key secret could itself contain a colon; only the first colon is the split point.
            ("app123.key456:secret:with:colons", "app123.key456", "secret:with:colons"),
        ],
    )
    def test_splits_on_first_colon(self, api_key: str, expected_username: str, expected_password: str) -> None:
        username, password = split_api_key(api_key)
        assert username == expected_username
        assert password == expected_password

    def test_missing_colon_yields_empty_password(self) -> None:
        username, password = split_api_key("no-colon-here")
        assert username == "no-colon-here"
        assert password == ""


class TestParseIntervalStart:
    @pytest.mark.parametrize(
        ("interval_id", "expected_iso"),
        [
            ("2024-01-15:14:05", "2024-01-15T14:05:00+00:00"),
            ("2024-01-15:14", "2024-01-15T14:00:00+00:00"),
            ("2024-01-15", "2024-01-15T00:00:00+00:00"),
        ],
    )
    def test_parses_known_granularities(self, interval_id: str, expected_iso: str) -> None:
        parsed = _parse_interval_start(interval_id)
        assert parsed is not None
        assert parsed.isoformat() == expected_iso

    @pytest.mark.parametrize("interval_id", [None, "", "not-a-date", "2024/01/15"])
    def test_returns_none_for_malformed_or_missing(self, interval_id: str | None) -> None:
        assert _parse_interval_start(interval_id) is None


class TestAddIntervalStart:
    def test_adds_parsed_fields(self) -> None:
        row = {"intervalId": "2024-01-15:14", "unit": "hour"}
        result = _add_interval_start(row)
        assert result["interval_start"] == "2024-01-15T14:00:00+00:00"
        # Unix ms — the same unit Ably's start/end stats params take.
        assert result["interval_start_ms"] == 1705327200000

    def test_missing_interval_id_sets_none_rather_than_raising(self) -> None:
        row: dict[str, Any] = {"unit": "hour"}
        result = _add_interval_start(row)
        assert result["interval_start"] is None
        assert result["interval_start_ms"] is None


class TestGetResource:
    def test_full_refresh_has_no_incremental_params(self) -> None:
        resource = get_resource("Stats", "hour", should_use_incremental_field=False)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        assert "incremental" not in endpoint
        assert resource["write_disposition"] == "replace"
        params = endpoint["params"]
        assert isinstance(params, dict)
        assert params["unit"] == "hour"
        assert params["direction"] == "forwards"

    def test_incremental_sets_start_and_end_params(self) -> None:
        resource = get_resource("Stats", "day", should_use_incremental_field=True)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        incremental = endpoint["incremental"]
        assert incremental is not None
        assert incremental["start_param"] == "start"
        assert incremental["end_param"] == "end"
        assert incremental["initial_value"] == "0"
        # end_value is bound to "now" at build time — assert it's a plausible ms-epoch, not a fixed literal.
        end_value = incremental["end_value"]
        assert end_value is not None and int(end_value) > 1_700_000_000_000
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_channels_asks_for_details_and_never_merges(self) -> None:
        # `by=value` is what makes /channels return objects instead of bare name strings, and the
        # endpoint has no time filter, so an incremental sync request must still write a replace.
        resource = get_resource("Channels", "hour", should_use_incremental_field=True)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        params = endpoint["params"]
        assert isinstance(params, dict)
        assert params["by"] == "value"
        assert "incremental" not in endpoint
        assert resource["write_disposition"] == "replace"


class TestAddChannelPath:
    @pytest.mark.parametrize(
        ("channel_id", "expected"),
        [
            ("plain-channel", "plain-channel"),
            # Ably channel names routinely carry these separators; an unencoded `/` would address
            # a different path once substituted into /channels/{channel_id}/messages.
            ("chat:room1", "chat%3Aroom1"),
            ("user/42/inbox", "user%2F42%2Finbox"),
            ("with space", "with%20space"),
        ],
    )
    def test_percent_encodes_reserved_characters(self, channel_id: str, expected: str) -> None:
        assert _add_channel_path({"channelId": channel_id})["channel_path"] == expected

    def test_missing_channel_id_adds_nothing(self) -> None:
        # The fan-out raises its own error naming the missing field; don't bind an empty path.
        assert "channel_path" not in _add_channel_path({"status": {}})


class TestAddMessageTime:
    def test_derives_iso_datetime_from_unix_ms(self) -> None:
        assert _add_message_time({"timestamp": 1705327200000})["message_time"] == "2024-01-15T14:00:00+00:00"

    @pytest.mark.parametrize("timestamp", [None, "1705327200000"])
    def test_missing_or_non_numeric_timestamp_sets_none(self, timestamp: Any) -> None:
        assert _add_message_time({"timestamp": timestamp})["message_time"] is None


class TestAblySourceResumeBehavior:
    """End-to-end resume/pagination behaviour of the Ably source."""

    def test_fresh_run_follows_link_header_and_saves_state(self) -> None:
        next_url = "https://main.realtime.ably.net/stats?start=abc&series=1"
        result = _driver().run(
            "Stats",
            [
                _page([{"intervalId": "2024-01-15:14", "unit": "hour"}], next_url=next_url),
                _page([{"intervalId": "2024-01-15:15", "unit": "hour"}]),
            ],
        )

        assert result.raised is None
        assert result.urls == ["https://main.realtime.ably.net/stats?limit=1000&direction=forwards&unit=hour", next_url]

        assert result.rows[0]["interval_start"] == "2024-01-15T14:00:00+00:00"
        assert result.rows[1]["interval_start"] == "2024-01-15T15:00:00+00:00"

        assert result.saved_states == [AblyResumeConfig(next_url=next_url)]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        result = _driver().run("Stats", [_page([{"intervalId": "2024-01-15:14", "unit": "hour"}])])

        assert result.raised is None
        assert result.saved_states == []

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        resumed_url = "https://main.realtime.ably.net/stats?start=resumed"
        result = _driver().run(
            "Stats",
            [_page([{"intervalId": "2024-01-15:16", "unit": "hour"}])],
            resume_state=AblyResumeConfig(next_url=resumed_url),
        )

        assert result.raised is None
        assert result.urls == [resumed_url]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("Stats", [_page([{"intervalId": "2024-01-15:14", "unit": "hour"}])])

        assert result.raised is None
        assert result.paths == ["/stats"]
        assert result.params("start") == [None]


class TestChannelFanout:
    """End-to-end behaviour of the channel-scoped endpoints, which fan out over ``/channels``."""

    def test_child_path_uses_the_encoded_channel_name(self) -> None:
        # An unencoded `/` in the channel name would address a different Ably endpoint.
        result = _driver().run(
            "ChannelMessages",
            [
                _page([{"channelId": "user/42/inbox", "status": {"isActive": True}}]),
                _page([{"id": "msg-1", "timestamp": 1705327200000}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/channels", "/channels/user%2F42%2Finbox/messages"]
        assert result.rows[0]["channel_id"] == "user/42/inbox"
        assert result.rows[0]["message_time"] == "2024-01-15T14:00:00+00:00"

    def test_message_history_is_windowed_and_ordered_forwards(self) -> None:
        # Ably history defaults to newest-first, which would walk the watermark backwards, and
        # every request needs an explicit end because there is no open-ended "since X" mode.
        result = _driver().run(
            "ChannelMessages",
            [
                _page([{"channelId": "chat", "status": {"isActive": True}}]),
                _page([{"id": "msg-1", "timestamp": 1705327200000}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1705327100000,
        )

        assert result.raised is None
        assert result.requests[1].param("direction") == "forwards"
        assert result.requests[1].param("start") == "1705327100000"
        assert int(result.requests[1].param("end") or 0) > 1_700_000_000_000

    def test_presence_sends_no_time_window_on_an_incremental_run(self) -> None:
        # Presence reports who is present now and exposes no time filter, so an incremental
        # request must not grow start/end params the API would reject or ignore.
        result = _driver().run(
            "Presence",
            [
                _page([{"channelId": "chat", "status": {"isActive": True}}]),
                _page([{"id": "pres-1", "clientId": "alice", "action": "PRESENT"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1705327100000,
        )

        assert result.raised is None
        assert result.requests[1].param("start") is None
        assert result.requests[1].param("end") is None
        assert result.rows[0]["channel_id"] == "chat"

    def test_parent_listing_asks_for_channel_details(self) -> None:
        result = _driver().run(
            "Presence",
            [
                _page([{"channelId": "chat", "status": {"isActive": True}}]),
                _page([]),
            ],
        )

        assert result.raised is None
        assert result.requests[0].param("by") == "value"

    def test_checkpoint_records_each_finished_channel(self) -> None:
        result = _driver().run(
            "Presence",
            [
                _page([{"channelId": "a"}, {"channelId": "b"}]),
                _page([{"id": "pres-a"}]),
                _page([{"id": "pres-b"}]),
            ],
        )

        assert result.raised is None
        saved = [state.fanout_state["completed"] for state in result.saved_states if state.fanout_state]
        assert saved[-1] == ["/channels/a/presence", "/channels/b/presence"]

    def test_resume_skips_channels_already_finished(self) -> None:
        result = _driver().run(
            "Presence",
            [
                _page([{"channelId": "a"}, {"channelId": "b"}]),
                _page([{"id": "pres-b"}]),
            ],
            resume_state=AblyResumeConfig(
                fanout_state={"completed": ["/channels/a/presence"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/channels", "/channels/b/presence"]
        assert [row["id"] for row in result.rows] == ["pres-b"]


class TestAblyHostPinningAndRedirects:
    """`allowed_hosts=[]` + `allow_redirects=False` keep the Basic-auth credential from
    following a spoofed ``Link: rel="next"`` target or a cross-origin redirect off Ably's host."""

    def test_off_origin_next_link_is_rejected_before_sending(self) -> None:
        # A spoofed `Link: rel="next"` pointing off Ably's host must be refused before the
        # request (carrying the Basic-auth key) leaves the process.
        evil_url = "https://evil.example.com/stats?start=abc"
        result = _driver().run("Stats", [_page([{"intervalId": "2024-01-15:14", "unit": "hour"}], next_url=evil_url)])

        # Only the legitimate first page was ever sent; the off-origin URL was never contacted.
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.paths == ["/stats"]

    def test_cross_origin_redirect_is_not_followed(self) -> None:
        result = _driver().run(
            "Stats", [ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/stats"})]
        )

        # The redirect target was never fetched: send ran once for the base host and stopped.
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()
        assert result.paths == ["/stats"]


class TestValidateCredentials:
    def test_malformed_key_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            ok, error = validate_credentials("no-colon-here", ABLY_VERSION_2)

        assert ok is False
        assert error is not None and "malformed" in error.lower()
        assert network.requests_log == []
        assert network.session_options == []

    @pytest.mark.parametrize(
        ("status_code", "expect_ok"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expect_ok: bool) -> None:
        answer = ScriptedResponse(status=status_code)
        script = always(answer) if status_code == 500 else [answer]
        with scripted_network(script) as network:
            ok, error = validate_credentials("app.key:secret", ABLY_VERSION_2)

        # The probe validates under the pinned version's header, not Ably's default.
        assert network.session_options[0]["headers"] == {"X-Ably-Version": "2"}
        assert network.requests_log[0].headers["x-ably-version"] == "2"
        assert ok is expect_ok
        if not expect_ok:
            assert error is not None

    def test_network_error_is_reported_not_raised(self) -> None:
        with scripted_network(always(RequestsConnectionError("boom"))):
            ok, error = validate_credentials("app.key:secret", ABLY_VERSION_2)

        assert ok is False
        assert error is not None and "boom" in error
