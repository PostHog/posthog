from products.warehouse_sources.sources.circleback._config import CirclebackSourceConfig
from products.warehouse_sources.sources.circleback.circleback import CIRCLEBACK_BASE_URL
from products.warehouse_sources.sources.circleback.source import CirclebackSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def _driver() -> SourceDriver:
    return SourceDriver(CirclebackSource(), CirclebackSourceConfig(api_key="cb_test"))


def _next_link(path_and_query: str) -> dict[str, str]:
    return {"Link": f'</api{path_and_query}>; rel="next"'}


class TestCirclebackSource:
    def test_meetings_request_every_accessible_meeting_and_drop_private_notes(self) -> None:
        result = _driver().run(
            "meetings",
            [
                ScriptedResponse(
                    json=[
                        {
                            "id": "mtg_a",
                            "name": "Planning",
                            "createdAt": "2026-01-05T10:00:00.000Z",
                            "privateNotes": "x",
                        },
                        {"id": "mtg_b", "name": "Review", "createdAt": "2026-01-06T10:00:00.000Z", "privateNotes": ""},
                    ]
                )
            ],
        )

        assert result.raised is None
        assert result.params("ownership") == ["All"]
        assert [row["id"] for row in result.rows] == ["mtg_a", "mtg_b"]
        assert all("privateNotes" not in row for row in result.rows)

    def test_action_items_read_the_done_pass_after_the_pending_pass(self) -> None:
        result = _driver().run(
            "action_items",
            [
                ScriptedResponse(
                    json=[{"id": 1, "status": "PENDING"}],
                    headers=_next_link("/action-items?assigneeType=Anyone&status=PENDING&cursor=c1"),
                ),
                ScriptedResponse(json=[{"id": 2, "status": "PENDING"}]),
                ScriptedResponse(json=[{"id": 3, "status": "DONE"}]),
            ],
        )

        assert result.raised is None
        assert result.params("status") == ["PENDING", "PENDING", "DONE"]
        assert result.params("assigneeType") == ["Anyone", "Anyone", "Anyone"]
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.saved_states[-1].next_url == f"{CIRCLEBACK_BASE_URL}/action-items?assigneeType=Anyone&status=DONE"

    def test_transcripts_carry_the_meeting_id_and_skip_a_meeting_that_is_gone(self) -> None:
        result = _driver().run(
            "transcripts",
            [
                ScriptedResponse(json=[{"id": "mtg_gone"}, {"id": "mtg_b"}]),
                ScriptedResponse(status=403, json={"error": "Cannot access meeting transcript."}),
                ScriptedResponse(json=[{"speaker": "Speaker one", "text": "Hello.", "timestamp": 1.5}]),
            ],
        )

        assert result.raised is None
        assert result.params("ownership")[0] == "All"
        assert result.paths[1:] == ["/api/meeting/mtg_gone/transcript", "/api/meeting/mtg_b/transcript"]
        assert result.rows == [{"speaker": "Speaker one", "text": "Hello.", "timestamp": 1.5, "meeting_id": "mtg_b"}]
