from typing import Any, cast

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.resend import (
    ResendAuthMethodConfig,
    ResendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend import ResendResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import ENDPOINTS, RESEND_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.source import ResendSource


def _driver() -> SourceDriver:
    config = ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="api_key", api_key="re_test"))
    return SourceDriver(ResendSource(), config)


def _page(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestEmailsPagination:
    def test_paginates_with_has_more_and_saves_state(self) -> None:
        page1 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2)]
        page2 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2, 4)]
        result = _driver().run(
            "emails",
            [
                _page({"data": page1, "has_more": True}),
                _page({"data": page2, "has_more": False}),
            ],
        )

        assert [r["id"] for r in result.rows] == ["e0", "e1", "e2", "e3"]
        assert len(result.requests) == 2
        # The `after` cursor advances from the last row's id of the previous page.
        assert result.requests[0].param("after") is None
        assert result.requests[0].param("limit") == "100"
        assert result.requests[1].param("after") == "e1"
        # First page is not terminal -> save next cursor; second page (has_more=False) -> no save.
        assert result.saved_states == [ResendResumeConfig(next_cursor="e1")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "emails",
            [_page({"data": [{"id": "e42"}], "has_more": False})],
            resume_state=ResendResumeConfig(next_cursor="e41"),
        )

        assert [r["id"] for r in result.rows] == ["e42"]
        assert result.requests[0].param("after") == "e41"

    def test_raises_when_empty_page_with_has_more_true(self) -> None:
        result = _driver().run("emails", [_page({"data": [], "has_more": True})])

        assert isinstance(result.raised, ValueError)
        assert "empty page but has_more=True" in str(result.raised)


class TestContactsFanOut:
    def test_fanout_injects_audience_id_and_checkpoints(self) -> None:
        result = _driver().run(
            "contacts",
            [
                _page({"data": [{"id": "aud_1"}, {"id": "aud_2"}]}),  # audiences
                _page({"data": [{"id": "c1", "email": "a@example.com"}]}),  # aud_1 contacts
                _page({"data": [{"id": "c2", "email": "b@example.com"}]}),  # aud_2 contacts
            ],
        )

        assert result.rows == [
            {"id": "c1", "email": "a@example.com", "_audience_id": "aud_1"},
            {"id": "c2", "email": "b@example.com", "_audience_id": "aud_2"},
        ]
        assert result.paths == ["/audiences", "/audiences/aud_1/contacts", "/audiences/aud_2/contacts"]
        # After finishing aud_1 a checkpoint marks its path completed, so a crash resumes on aud_2.
        assert any(
            state.fanout_state is not None
            and any("audiences/aud_1/contacts" in p for p in state.fanout_state["completed"])
            for state in result.saved_states
        )

    def test_fanout_full_resync_when_completed_parent_absent(self) -> None:
        # If the completed audience no longer exists (e.g. deleted between syncs) no current parent
        # matches the stale path, so every present audience is fetched — no silent data loss.
        result = _driver().run(
            "contacts",
            [
                _page({"data": [{"id": "aud_1"}, {"id": "aud_2"}]}),
                _page({"data": [{"id": "c1"}]}),
                _page({"data": [{"id": "c2"}]}),
            ],
            resume_state=ResendResumeConfig(
                fanout_state={"completed": ["/audiences/aud_deleted/contacts"], "current": None, "child_state": None}
            ),
        )

        assert sorted(r["_audience_id"] for r in result.rows) == ["aud_1", "aud_2"]


class TestBroadcastClickedLinksFanOut:
    def test_pages_each_broadcast_and_skips_missing_broadcast(self) -> None:
        result = _driver().run(
            "broadcast_clicked_links",
            [
                _page({"data": [{"id": "b_1"}, {"id": "b_gone"}, {"id": "b_2"}]}),  # broadcasts
                _page({"data": [{"id": "o0", "url": "https://example.com/a", "clicks": 3}], "has_more": True}),
                _page({"data": [{"id": "o1", "url": "https://example.com/b", "clicks": 1}], "has_more": False}),
                _page({"message": "not found"}, status_code=404),
                _page({"data": [{"id": "o0", "url": "https://example.com/a", "clicks": 7}], "has_more": False}),
            ],
        )

        assert [(r["_broadcast_id"], r["url"], r["clicks"]) for r in result.rows] == [
            ("b_1", "https://example.com/a", 3),
            ("b_1", "https://example.com/b", 1),
            ("b_2", "https://example.com/a", 7),
        ]
        assert all("_broadcasts_id" not in r for r in result.rows)
        assert [(request.path, request.param("after")) for request in result.requests[1:]] == [
            ("/broadcasts/b_1/clicked-links", None),
            ("/broadcasts/b_1/clicked-links", "o0"),
            ("/broadcasts/b_gone/clicked-links", None),
            ("/broadcasts/b_2/clicked-links", None),
        ]
        assert result.requests[1].param("limit") == "100"


class TestEmailMetrics:
    @time_machine.travel("2026-10-08T12:00:00Z", tick=False)
    def test_requests_daily_breakdown_and_yields_one_row_per_day(self) -> None:
        result = _driver().run(
            "email_metrics",
            [
                _page(
                    {
                        "object": "metrics",
                        "totals": {"sent": 5},
                        "data": [{"period": "2026-10-07", "sent": 2}, {"period": "2026-10-08", "sent": 3}],
                    }
                )
            ],
        )

        assert result.rows == [{"period": "2026-10-07", "sent": 2}, {"period": "2026-10-08", "sent": 3}]
        assert result.paths == ["/emails/metrics"]
        assert dict(result.requests[0].query) == {
            "dimensions": ("period",),
            "granularity": ("daily",),
            "timezone": ("UTC",),
            "start_date": ("2016-10-10",),
        }


class TestRetryable:
    def test_401_does_not_retry_and_raises(self) -> None:
        result = _driver().run("audiences", [_page({"message": "unauthorized"}, status_code=401)])

        assert result.raised is not None
        assert len(result.requests) == 1


class TestResumeConfigCompatibility:
    def test_old_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved by the
        # pre-framework implementation must keep loading after the migration.
        state = ResendResumeConfig(**cast("dict[str, Any]", {"next_cursor": "e1", "last_completed_parent_id": "aud_2"}))
        assert state.next_cursor == "e1"
        assert state.last_completed_parent_id == "aud_2"
        assert state.fanout_state is None


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_page({"data": []})))

        config = RESEND_ENDPOINTS[endpoint]
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
