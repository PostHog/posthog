import json
from typing import Any

from parameterized import parameterized

from products.replay_vision.backend.temporal.network_capture import MAX_REQUESTS_PER_SESSION, parse_network_payload


def _line(*events: dict[str, Any], window_id: str = "w1") -> str:
    return json.dumps({"window_id": window_id, "data": list(events)})


def _rrweb_event(timestamp: int, *requests: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": 6,
        "timestamp": timestamp,
        "data": {"plugin": "rrweb/network@1", "payload": {"requests": list(requests)}},
    }


def _posthog_event(timestamp: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": 6, "timestamp": timestamp, "data": {"plugin": "posthog/network@1", "payload": payload}}


class TestParseNetworkPayload:
    def test_decodes_named_rrweb_requests(self) -> None:
        payload = parse_network_payload(
            [
                _line(
                    _rrweb_event(
                        1000,
                        {"name": "https://app.test/api/save", "method": "POST", "status": 500, "duration": 42},
                    )
                )
            ]
        )
        assert payload.captured
        assert len(payload.requests) == 1
        request = payload.requests[0]
        assert request.url == "https://app.test/api/save"
        assert request.method == "POST"
        assert request.status == 500
        assert request.duration_ms == 42
        assert request.timestamp_ms == 1000

    def test_decodes_index_encoded_posthog_requests(self) -> None:
        # posthog/network@1 encodes fields by position, so a dropped index mapping silently yields nothing.
        payload = parse_network_payload([_line(_posthog_event(2000, {"2": "https://app.test/slow", "39": 4000}))])
        assert len(payload.requests) == 1
        assert payload.requests[0].url == "https://app.test/slow"
        assert payload.requests[0].duration_ms == 4000

    @parameterized.expand(
        [
            ("server error", {"status": 500, "duration": 10}, True),
            ("client error", {"status": 404, "duration": 10}, True),
            ("never completed", {"status": 0, "duration": 10}, True),
            ("slow success", {"status": 200, "duration": 4000}, True),
            ("fast success", {"status": 200, "duration": 30}, False),
            ("fast redirect", {"status": 302, "duration": 12}, False),
        ]
    )
    def test_keeps_only_failed_or_slow_requests(self, _label: str, fields: dict[str, Any], kept: bool) -> None:
        payload = parse_network_payload([_line(_rrweb_event(1000, {"name": "https://app.test/x", **fields}))])
        assert bool(payload.requests) is kept

    def test_wrapped_fetch_status_wins_over_the_observer_status(self) -> None:
        # Both fields can arrive on one request, in either key order. Losing this precedence misreports a
        # failed request as a successful one, which is the whole signal the tool exists for.
        payload = parse_network_payload(
            [
                _line(
                    _rrweb_event(
                        1000,
                        {"name": "https://app.test/a", "responseStatus": 200, "status": 503, "duration": 5},
                    ),
                    _rrweb_event(
                        2000,
                        {"name": "https://app.test/b", "status": 503, "responseStatus": 200, "duration": 5},
                    ),
                )
            ]
        )
        assert [request.status for request in payload.requests] == [503, 503]

    def test_drops_query_string_headers_and_bodies(self) -> None:
        # These carry tokens and other people's personal data. They must never reach the model or the
        # stored observation, whatever the plugin sent.
        payload = parse_network_payload(
            [
                _line(
                    _rrweb_event(
                        1000,
                        {
                            "name": "https://app.test/api/search?q=someone%40example.com&token=sekret#frag",
                            "status": 500,
                            "requestHeaders": {"authorization": "Bearer sekret"},
                            "requestBody": "password=hunter2",
                            "responseBody": "contact: someone@example.com",
                        },
                    )
                )
            ]
        )
        request = payload.requests[0]
        assert request.url == "https://app.test/api/search"
        serialized = request.model_dump_json()
        assert "sekret" not in serialized
        assert "example.com" not in serialized
        assert "hunter2" not in serialized

    def test_reports_capture_absent_separately_from_no_failures(self) -> None:
        # A recording with capture off must not read as "nothing failed".
        no_capture = parse_network_payload([_line({"type": 3, "timestamp": 1000, "data": {"source": 2}})])
        assert not no_capture.captured
        assert no_capture.requests == []

        captured_but_clean = parse_network_payload(
            [_line(_rrweb_event(1000, {"name": "https://app.test/ok", "status": 200, "duration": 5}))]
        )
        assert captured_but_clean.captured
        assert captured_but_clean.requests == []

    def test_survives_corrupt_lines_and_unusable_requests(self) -> None:
        payload = parse_network_payload(
            [
                "not json at all",
                "",
                json.dumps({"window_id": "w1"}),
                _line(_rrweb_event(1000, {"status": 500})),  # no URL
                _line(_rrweb_event(2000, {"name": "https://app.test/api/ok", "status": 503})),
            ]
        )
        assert [request.url for request in payload.requests] == ["https://app.test/api/ok"]

    def test_caps_and_orders_by_timestamp(self) -> None:
        events = [
            _rrweb_event(10_000 - index, {"name": f"https://app.test/{index}", "status": 500})
            for index in range(MAX_REQUESTS_PER_SESSION + 10)
        ]
        payload = parse_network_payload([_line(event) for event in events])
        assert len(payload.requests) == MAX_REQUESTS_PER_SESSION
        assert payload.truncated
        timestamps = [request.timestamp_ms for request in payload.requests]
        assert timestamps == sorted(timestamps)
