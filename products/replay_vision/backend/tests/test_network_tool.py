import datetime as dt
from dataclasses import dataclass
from typing import Any

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


@dataclass
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

    def test_empty_index_when_the_recording_start_is_unknown(self) -> None:
        assert build_network_index(_payload(10), None, _IDENTITY_CLOCK).offsets == []

    def test_caps_to_the_requests_nearest_vid_t(self) -> None:
        index = build_network_index(_payload(*range(0, 60)), _SESSION_START, _IDENTITY_CLOCK)
        returned = [entry["vid_t"] for entry in get_network_around(index, 30, 60)["requests"]]
        assert len(returned) == 20
        assert returned == sorted(returned)
        assert 30 in returned


class TestHasRequests:
    # Decides whether the tool is offered at all, so a wrong answer either hides real evidence or spends
    # a shared lookup budget on calls that can never return anything.
    def test_true_only_when_there_is_something_to_return(self) -> None:
        assert build_network_index(_payload(10), _SESSION_START, _IDENTITY_CLOCK).has_requests()
        assert not build_network_index(_payload(), _SESSION_START, _IDENTITY_CLOCK).has_requests()
        assert not build_network_index(None, _SESSION_START, _IDENTITY_CLOCK).has_requests()


class TestDispatchNetworkTool:
    def test_dispatches_a_valid_call(self) -> None:
        index = build_network_index(_payload(12), _SESSION_START, _IDENTITY_CLOCK)
        result = dispatch_network_tool(_Call(name=GET_NETWORK_TOOL_NAME, args={"vid_t": 12}), index)
        assert [entry["url"] for entry in result["requests"]] == ["https://app.test/12"]

    def test_a_malformed_argument_answers_the_model_instead_of_failing_the_scan(self) -> None:
        index = build_network_index(_payload(12), _SESSION_START, _IDENTITY_CLOCK)
        result = dispatch_network_tool(_Call(name=GET_NETWORK_TOOL_NAME, args={"vid_t": "nope"}), index)
        assert "error" in result
