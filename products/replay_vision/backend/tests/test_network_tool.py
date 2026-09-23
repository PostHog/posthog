import datetime as dt
from dataclasses import dataclass
from typing import Any

from parameterized import parameterized

from products.replay_vision.backend.temporal.network_capture import NetworkRequest, SessionNetworkPayload
from products.replay_vision.backend.temporal.network_tool import (
    GET_NETWORK_TOOL_NAME,
    build_network_index,
    dispatch_network_tool,
    get_network_around,
)
from products.replay_vision.backend.temporal.video_clock import ActiveSpan, VideoClock

_SESSION_START = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_IDENTITY_CLOCK = VideoClock(spans=())


def _start_ms() -> int:
    return int(_SESSION_START.timestamp() * 1000)


def _payload(*offsets_s: int, captured: bool = True) -> SessionNetworkPayload:
    return SessionNetworkPayload(
        requests=[
            NetworkRequest(
                timestamp_ms=_start_ms() + offset * 1000,
                url=f"https://app.test/{offset}",
                status=500,
                method="GET",
            )
            for offset in offsets_s
        ],
        captured=captured,
    )


@dataclass(frozen=True)
class _Call:
    name: str
    args: dict[str, Any]


class TestGetNetworkAround:
    def test_resolves_vid_t_through_the_video_clock(self) -> None:
        # The anchor has to match the video footer and the events tool, or a REC_T addresses different
        # moments in the two tools.
        index = build_network_index(_payload(30), _SESSION_START, _IDENTITY_CLOCK)
        assert index.offsets == [30]
        assert get_network_around(index, 30)["requests"][0]["vid_t"] == 30

    def test_projects_across_a_stretch_the_rasterizer_cut(self) -> None:
        # The render drops inactive stretches, so a request's session time runs ahead of its video time.
        # Indexing it on the session clock would place it at a moment the model never sees.
        clock = VideoClock(
            spans=(
                ActiveSpan(session_from_s=0, session_to_s=10, video_from_s=0, video_to_s=10),
                ActiveSpan(session_from_s=100, session_to_s=110, video_from_s=10, video_to_s=20),
            )
        )
        index = build_network_index(_payload(105), _SESSION_START, clock)
        assert index.offsets == [15]

    def test_returns_only_requests_within_the_window(self) -> None:
        index = build_network_index(_payload(0, 20, 21, 40), _SESSION_START, _IDENTITY_CLOCK)
        assert [entry["vid_t"] for entry in get_network_around(index, 20, 5)["requests"]] == [20, 21]

    def test_an_empty_window_says_so(self) -> None:
        result = get_network_around(build_network_index(_payload(500), _SESSION_START, _IDENTITY_CLOCK), 10)
        assert result["requests"] == []
        assert "No failed or slow requests" in result["note"]

    def test_an_incomplete_read_never_claims_the_window_was_clean(self) -> None:
        # Truncation is what produces wrongly empty windows, so the affirmative note must not win there.
        payload = SessionNetworkPayload(
            requests=[NetworkRequest(timestamp_ms=_start_ms(), url="https://app.test/x", status=500)],
            captured=True,
            truncated=True,
        )
        result = get_network_around(build_network_index(payload, _SESSION_START, _IDENTITY_CLOCK), 400)
        assert result["requests"] == []
        assert "may be incomplete" in result["note"]

    def test_empty_index_when_the_recording_start_is_unknown(self) -> None:
        assert build_network_index(_payload(10), None, _IDENTITY_CLOCK).offsets == []

    def test_caps_to_the_requests_nearest_vid_t(self) -> None:
        index = build_network_index(_payload(*range(0, 60)), _SESSION_START, _IDENTITY_CLOCK)
        returned = [entry["vid_t"] for entry in get_network_around(index, 30, 60)["requests"]]
        assert len(returned) == 20
        assert returned == sorted(returned)
        assert 30 in returned


class TestIndexState:
    # The state and the offer decision come from one object, so the preamble cannot promise a tool the
    # conversation does not carry.
    @parameterized.expand(
        [
            ("requests to show", _payload(10), "available", True),
            ("captured, none failed", _payload(captured=True), "clean", False),
            (
                "captured but a block was unreadable",
                SessionNetworkPayload(captured=True, partial=True),
                "none",
                False,
            ),
            (
                "captured but truncated",
                SessionNetworkPayload(captured=True, truncated=True),
                "none",
                False,
            ),
            ("no capture at all", _payload(captured=False), "none", False),
            ("no payload", None, "none", False),
        ]
    )
    def test_state_and_offer_agree(
        self, _label: str, payload: SessionNetworkPayload | None, expected: str, offered: bool
    ) -> None:
        index = build_network_index(payload, _SESSION_START, _IDENTITY_CLOCK)
        assert index.state() == expected
        assert index.has_requests() is offered


class TestDispatchNetworkTool:
    def test_dispatches_a_valid_call(self) -> None:
        index = build_network_index(_payload(12), _SESSION_START, _IDENTITY_CLOCK)
        result = dispatch_network_tool(_Call(name=GET_NETWORK_TOOL_NAME, args={"vid_t": 12}), index)
        assert [entry["url"] for entry in result["requests"]] == ["https://app.test/12"]

    def test_an_unknown_tool_name_is_refused(self) -> None:
        # A hallucinated name, or one whose tool was not offered, must not return data for a question the
        # model did not ask.
        index = build_network_index(_payload(12), _SESSION_START, _IDENTITY_CLOCK)
        result = dispatch_network_tool(_Call(name="get_something_else", args={"vid_t": 12}), index)
        assert "error" in result

    def test_a_malformed_argument_answers_the_model_instead_of_failing_the_scan(self) -> None:
        index = build_network_index(_payload(12), _SESSION_START, _IDENTITY_CLOCK)
        result = dispatch_network_tool(_Call(name=GET_NETWORK_TOOL_NAME, args={"vid_t": "nope"}), index)
        assert "error" in result
