import json
from typing import Any

from parameterized import parameterized

from products.replay_vision.backend.temporal.network_capture import (
    MAX_REQUESTS_PER_SESSION,
    NetworkCollector,
    parse_network_payload,
)


def _line(event: dict[str, Any], window_id: str = "w1") -> str:
    return json.dumps([window_id, event])


def _api_line(*events: dict[str, Any], window_id: str = "w1") -> str:
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
                    )
                ),
                _line(
                    _rrweb_event(
                        2000,
                        {"name": "https://app.test/b", "status": 503, "responseStatus": 200, "duration": 5},
                    )
                ),
            ]
        )
        assert [request.status for request in payload.requests] == [503, 503]

    @parameterized.expand(
        [
            ("name only", {"name": "https://app.test/a"}, "https://app.test/a"),
            ("url only", {"url": "https://app.test/b"}, "https://app.test/b"),
            ("name wins over url", {"url": "https://app.test/b", "name": "https://app.test/a"}, "https://app.test/a"),
        ]
    )
    def test_accepts_the_url_key_wrapped_fetch_uses(self, _label: str, fields: dict[str, Any], expected: str) -> None:
        # Wrapped fetch and xhr report `url` rather than `name`. Dropping those loses exactly the failed
        # requests the tool exists to surface, and the recording still looks like it captured nothing.
        payload = parse_network_payload([_line(_rrweb_event(1000, {"status": 500, **fields}))])
        assert [request.url for request in payload.requests] == [expected]

    def test_strips_credentials_from_the_authority(self) -> None:
        # A URL can carry `user:token@` before the host, which a netloc-preserving rebuild keeps.
        payload = parse_network_payload(
            [_line(_rrweb_event(1000, {"name": "https://someone:sekret@app.test/api/x", "status": 500}))]
        )
        assert payload.requests[0].url == "https://app.test/api/x"
        assert "sekret" not in payload.requests[0].model_dump_json()

    @parameterized.expand(
        [
            ("unparseable host", "http://[bad/api?token=sekret"),
            ("unparseable host with userinfo", "http://someone:sekret@[bad/api"),
            ("port out of range", "http://someone:sekret@app.test:99999/api?q=sekret"),
            ("non-numeric port", "http://someone:sekret@app.test:abc/api"),
        ]
    )
    def test_a_url_the_parser_rejects_still_loses_its_secrets(self, _label: str, malformed: str) -> None:
        # The structured path cannot run on these, and `.port` raises on the last two. Either way the
        # request must still be reported, without the credential or the query.
        payload = parse_network_payload([_line(_rrweb_event(1000, {"name": malformed, "status": 500}))])
        assert len(payload.requests) == 1, "a malformed URL must not drop the request"
        assert "sekret" not in payload.requests[0].url

    def test_records_a_partial_read_when_asked(self) -> None:
        # A block that failed to fetch makes "nothing failed" unprovable, so the payload has to say so.
        collector = NetworkCollector()
        collector.feed([_line(_rrweb_event(1000, {"name": "https://app.test/ok", "status": 200, "duration": 5}))])
        assert collector.finish().captured
        assert not collector.finish().partial
        assert collector.finish(partial=True).partial

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

    def test_an_unrecognized_array_is_ignored_not_misread(self) -> None:
        # A two-event list matches a [window_id, event] pair by length. Reading it as one would keep the
        # second event and silently drop the first, inventing a request the line never described.
        both = json.dumps(
            [
                _rrweb_event(1000, {"name": "https://app.test/first", "status": 500}),
                _rrweb_event(2000, {"name": "https://app.test/second", "status": 503}),
            ]
        )
        payload = parse_network_payload([both])
        assert payload.requests == []
        assert payload.captured is False

    def test_reads_the_api_wrapper_shape_too(self) -> None:
        payload = parse_network_payload(
            [_api_line(_rrweb_event(1000, {"name": "https://app.test/api/x", "status": 503}))]
        )
        assert [request.url for request in payload.requests] == ["https://app.test/api/x"]

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
