from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.goldcast import (
    GoldcastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.goldcast import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import GOLDCAST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source import GoldcastSource


def _driver(access_key: str = "tok") -> SourceDriver:
    return SourceDriver(GoldcastSource(), GoldcastSourceConfig(access_key=access_key))


class TestTopLevelEndpoints:
    def test_broadcasts_drop_stream_credentials(self) -> None:
        result = _driver().run(
            "broadcasts",
            [
                ScriptedResponse(
                    json=[
                        {
                            "id": "b1",
                            "title": "Keynote",
                            "youtube_stream_key": "yt-fake-key",
                            "facebook_stream_key": "fb-fake-key",
                            "custom_stream_key": "custom-fake-key",
                            "external_rtmp_push_stream": "rtmp://stream.example.com/live/fake-key",
                            "wordly_session_key": "wordly-fake-key",
                            "medialive_rtmp_input_details": {"in_stream_key": "rtmp-fake-key"},
                        }
                    ]
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "b1", "title": "Keynote"}]


class TestFanOut:
    @parameterized.expand(
        [
            ("webinars", "/event/", "/event/webinars/p1/", "event"),
            ("speakers", "/event/", "/event/p1/public/v1/speakers/", "event"),
            ("broadcast_polls", "/event/broadcasts/", "/event/broadcasts/p1/polls/", "broadcast"),
        ]
    )
    def test_child_request_binds_parent_id_and_stamps_it(
        self, endpoint: str, parent_path: str, child_path: str, parent_field: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"id": "p1"}]), ScriptedResponse(json=[{"id": "c1"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "c1", parent_field: "p1"}]
        assert result.paths == [parent_path, child_path]
        assert [request.origin for request in result.requests] == ["https://customapi.goldcast.io"] * 2

    def test_child_non_404_error_propagates(self) -> None:
        result = _driver().run(
            "webinars",
            [ScriptedResponse(json=[{"id": "e1"}]), ScriptedResponse(status=403, json={"detail": "Forbidden"})],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_event_missing_id_key_fails_loudly(self) -> None:
        # A malformed parent event (missing the required `id` fan-out key) must raise rather than
        # silently under-sync that event's children with no signal.
        result = _driver().run("webinars", [ScriptedResponse(json=[{"name": "no id"}])])

        assert isinstance(result.raised, KeyError)

    @parameterized.expand([("empty_string", ""), ("none", None), ("zero", 0)])
    def test_event_with_falsy_id_fails_loudly(self, _name: str, falsy_id: Any) -> None:
        # A falsy `id` (empty string, None, 0) must raise too — silently skipping it would
        # under-sync that event's children exactly like a missing key would.
        result = _driver().run("webinars", [ScriptedResponse(json=[{"id": falsy_id}])])

        assert isinstance(result.raised, ValueError)


class TestAuthAndRedaction:
    def test_sync_session_redacts_token_and_skips_sample_capture(self) -> None:
        # The token rides in the non-standard `Token` auth header the name-based scrubbers can't
        # recognise, so it must be registered for value-based redaction on the tracked session.
        result = _driver("super-secret").run("events", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.session_options[0].get("redact_values") == ("Token super-secret",)
        # Broadcast and webinar bodies carry stream keys the sample scrubber can't recognise.
        assert result.session_options[0].get("capture") is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("events", ["id"], "created_at"),
            ("organizations", ["id"], "created_at"),
            # agenda_items has no creation timestamp, so it must not be partitioned.
            ("agenda_items", ["id"], None),
            # Fan-out children carry the parent id in a composite key for table-wide uniqueness.
            ("webinars", ["event", "id"], "created_at"),
            ("event_members", ["event", "id"], "created_at"),
        ]
    )
    def test_partition_and_primary_keys_per_endpoint(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
        if partition_key is None:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
        else:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [partition_key]

    def test_every_endpoint_declares_a_primary_key(self) -> None:
        # A non-unique / missing key seeds duplicate rows that make every later merge multi-match.
        for name, config in GOLDCAST_ENDPOINTS.items():
            assert config.primary_keys, f"{name} has no primary key"


class TestValidateCredentials:
    @parameterized.expand([("not_found", 404)])
    def test_non_200_returns_false(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("tok") is False

        assert network.requests_log[0].path == "/core/organization/"

    def test_probe_registers_token_for_redaction_and_uses_token_scheme(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": "org"})]) as network:
            assert validate_credentials("super-secret") is True

        assert network.session_options[0].get("redact_values") == ("super-secret",)
        assert network.requests_log[0].headers["authorization"] == "Token super-secret"
