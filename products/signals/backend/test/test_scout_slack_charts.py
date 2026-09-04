import json
from contextlib import nullcontext
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from posthog.redis import get_client

from products.exports.backend.facade.api import RENDER_TIMEOUT
from products.signals.backend.models import SignalReport, SignalScoutRun
from products.signals.backend.scout_harness.slack_charts import (
    CHART_BLOCK_ID_PREFIX,
    MAX_SLACK_REPORT_CHARTS,
    SLACK_REPORT_CHART_RENDER_BUDGET_SECONDS,
    SLACK_REPORT_CHART_URL_TTL,
    ChartRenderBudget,
    _rendered_asset_entry_key,
    _rendered_assets_cache_key,
    build_scout_report_chart_blocks,
)
from products.signals.backend.scout_harness.slack_delivery import build_scout_report_slack_message

_TRENDS = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]}}
_SAVED = {"kind": "SavedInsightNode", "shortId": "abc123xy"}
_SQL = {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}


def _chart(chart_id: str, query: dict, **extra: object) -> dict:
    return {"chart_id": chart_id, "title": f"Chart {chart_id}", "query": query, **extra}


class TestScoutSlackReportCharts(BaseTest):
    def _make_run(self, *, created_by=None) -> SignalScoutRun:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            created_by=created_by,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        return SignalScoutRun.all_teams.create(
            task_run=task_run, team=self.team, skill_name="signals-scout-product-analytics", skill_version=1
        )

    def _make_report(self, charts: list[dict], summary: str = "Signups dropped.") -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Signups", summary=summary, charts=charts
        )

    def _patched_render(self):
        render = patch("products.exports.backend.facade.api.render_png_export")
        url = patch("products.exports.backend.facade.api.get_delivery_image_url")
        return render, url

    def test_renders_supported_charts_and_skips_the_rest_without_failing(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report(
            [
                _chart("trend", _TRENDS, caption="Daily signups, last 30 days"),
                _chart("sql", _SQL),
                _chart("saved", _SAVED),
                _chart("broken", _TRENDS),
            ]
        )
        assets = iter(
            [(MagicMock(id=11), b"png"), (MagicMock(id=12), b"png"), (MagicMock(id=13, exception="boom"), None)]
        )
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.side_effect = lambda **_: next(assets)
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            blocks = build_scout_report_chart_blocks(report, run)

        assert [call.kwargs.get("insight_short_id") for call in render_mock.call_args_list] == [None, "abc123xy", None]
        assert render_mock.call_args_list[0].kwargs["export_context"] == {"source": _TRENDS}
        assert render_mock.call_args_list[0].kwargs["created_by"] == self.user
        # A delivery render is a system asset that expires with its url, not a user export kept for months.
        for call in render_mock.call_args_list:
            assert call.kwargs["is_system"] is True
            assert abs(call.kwargs["expires_after"] - timezone.now() - SLACK_REPORT_CHART_URL_TTL) < timedelta(
                minutes=1
            )
        # Every URL mint is pinned to the acting user, so a substituted cache id can't be published.
        assert all(call.kwargs["created_by_id"] == self.user.id for call in url_mock.call_args_list)
        assert [{k: v for k, v in b.items() if k != "block_id"} for b in blocks if b["type"] == "image"] == [
            {"type": "image", "image_url": "https://img/11", "alt_text": "Chart trend"},
            {"type": "image", "image_url": "https://img/12", "alt_text": "Chart saved"},
        ]
        assert blocks[2]["elements"] == [{"type": "mrkdwn", "text": "Daily signups, last 30 days"}]
        # Every block a chart contributes is tagged, so a message Slack refuses can drop them whole.
        assert all(b["block_id"].startswith(CHART_BLOCK_ID_PREFIX) for b in blocks)

    def test_referenced_charts_render_first_and_the_cap_holds(self) -> None:
        run = self._make_run(created_by=self.user)
        charts = [_chart(f"c{i}", _TRENDS) for i in range(MAX_SLACK_REPORT_CHARTS + 2)]
        report = self._make_report(charts, summary="See [the last one](chart:c4) and [c1](chart:c1).")
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.return_value = "https://img/1"
            blocks = build_scout_report_chart_blocks(report, run)

        titles = [b["text"]["text"] for b in blocks if b["type"] == "section"]
        assert titles == ["*Chart c4*", "*Chart c1*", "*Chart c0*"]
        assert render_mock.call_count == MAX_SLACK_REPORT_CHARTS

    @parameterized.expand(
        [
            ("no_acting_user", None),
            ("deactivated_acting_user", "inactive"),
            ("acting_user_without_project_access", "no_project_access"),
            ("no_charts", "user"),
        ]
    )
    def test_returns_nothing_without_a_principal_or_charts(self, _name, actor) -> None:
        if actor == "inactive":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        access_patch = (
            patch("products.signals.backend.scout_harness.slack_charts.Team.all_users_with_access")
            if actor == "no_project_access"
            else nullcontext()
        )
        run = self._make_run(created_by=self.user if actor else None)
        report = self._make_report([_chart("trend", _TRENDS)] if actor != "user" else [])
        render, url = self._patched_render()
        with render as render_mock, url, access_patch as access_mock:
            if access_mock is not None:
                access_mock.return_value.filter.return_value.exists.return_value = False
            assert build_scout_report_chart_blocks(report, run) == []
        render_mock.assert_not_called()

    def test_failed_renders_count_toward_the_cap(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart(f"c{i}", _TRENDS) for i in range(MAX_SLACK_REPORT_CHARTS + 3)])
        render, url = self._patched_render()
        with render as render_mock, url:
            render_mock.return_value = (MagicMock(id=1, exception="boom"), None)
            assert build_scout_report_chart_blocks(report, run) == []
        assert render_mock.call_count == MAX_SLACK_REPORT_CHARTS

    def test_retry_of_the_same_delivery_reuses_rendered_assets(self) -> None:
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS), _chart("b", _TRENDS)])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.side_effect = [(MagicMock(id=7), b"png"), (MagicMock(id=8, exception="boom"), None)]
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            first = build_scout_report_chart_blocks(report, run, delivery_id="delivery-1")
            render_mock.side_effect = [(MagicMock(id=9), b"png")]
            second = build_scout_report_chart_blocks(report, run, delivery_id="delivery-1")

        assert [b["image_url"] for b in first if b["type"] == "image"] == ["https://img/7"]
        # Only the chart that failed the first time renders again; the other reuses asset 7.
        assert [b["image_url"] for b in second if b["type"] == "image"] == ["https://img/7", "https://img/9"]
        assert render_mock.call_count == 3

    def test_url_mint_failure_skips_the_chart_but_keeps_the_rest(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS), _chart("b", _TRENDS)])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.side_effect = [RuntimeError("db down"), "https://img/1"]
            blocks = build_scout_report_chart_blocks(report, run)

        assert [b["image_url"] for b in blocks if b["type"] == "image"] == ["https://img/1"]

    def test_retry_re_renders_a_chart_whose_query_changed(self) -> None:
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS)])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.side_effect = [(MagicMock(id=7), b"png"), (MagicMock(id=8), b"png")]
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            build_scout_report_chart_blocks(report, run, delivery_id="delivery-3")
            report.charts = [_chart("a", {**_TRENDS, "source": {"kind": "TrendsQuery", "series": [{"event": "x"}]}})]
            report.save(update_fields=["charts"])
            second = build_scout_report_chart_blocks(report, run, delivery_id="delivery-3")

        assert [b["image_url"] for b in second if b["type"] == "image"] == ["https://img/8"]

    def test_tampered_cache_entry_is_rejected_and_rerenders(self) -> None:
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS)])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.side_effect = [(MagicMock(id=7), b"png"), (MagicMock(id=9), b"png")]
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            build_scout_report_chart_blocks(report, run, delivery_id="delivery-tamper")
            # Simulate a shared-Redis writer swapping the cached asset id (keeping the old signature).
            key = _rendered_assets_cache_key("delivery-tamper")
            cached = get_client().get(key)
            assert cached is not None
            entry = json.loads(cached)
            (only_key,) = entry.keys()
            entry[only_key][0] = 999
            get_client().set(key, json.dumps(entry))
            second = build_scout_report_chart_blocks(report, run, delivery_id="delivery-tamper")

        # The forged id (999) fails the HMAC check and is treated as a miss, so the chart re-renders.
        assert [b["image_url"] for b in second if b["type"] == "image"] == ["https://img/9"]
        assert render_mock.call_count == 2

    @parameterized.expand(
        [
            # Rotation: the entry was signed with a key that is now the fallback, so reuse survives.
            ("rotated_signing_key", ["new-key", "signing-key"], 1),
            # Unprovisioned: nothing can verify an entry, so the delivery re-renders instead.
            ("no_signing_key", [], 2),
        ]
    )
    def test_cache_reuse_follows_the_signing_keys(self, _name, keys_on_read, expected_renders) -> None:
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS)])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.side_effect = [(MagicMock(id=7), b"png"), (MagicMock(id=9), b"png")]
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            with self.settings(SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS=["signing-key"]):
                build_scout_report_chart_blocks(report, run, delivery_id="delivery-keys")
            with self.settings(SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS=keys_on_read):
                build_scout_report_chart_blocks(report, run, delivery_id="delivery-keys")

        assert render_mock.call_count == expected_renders

    def test_shared_budget_carries_the_render_time_across_builds(self) -> None:
        run = self._make_run(created_by=self.user)
        # The edit a rebuild reacts to placed a new chart ahead of one the first build rendered.
        report = self._make_report([_chart("new", _TRENDS), _chart("kept", _TRENDS)])
        budget = ChartRenderBudget(started=1.0)
        budget.rendered_assets[_rendered_asset_entry_key("kept", _TRENDS)] = 7
        render, url = self._patched_render()
        # The budget started a whole window ago, so a rebuild sharing it has no time left and renders
        # nothing — proving the budget is measured from when it opened, not fresh per build. Reusing
        # an asset it already rendered costs no time, so the chart behind the new one still shows.
        with render as render_mock, url as url_mock:
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            blocks = build_scout_report_chart_blocks(
                report,
                run,
                clock=lambda: SLACK_REPORT_CHART_RENDER_BUDGET_SECONDS,
                budget=budget,
            )

        assert render_mock.call_count == 0
        assert [b["image_url"] for b in blocks if b["type"] == "image"] == ["https://img/7"]

    @parameterized.expand(
        [
            ("retry_cache_on", ["signing-key"]),
            # Unprovisioned key: the rebuild can only keep the unchanged charts from the budget itself.
            ("retry_cache_off", []),
        ]
    )
    def test_shared_budget_carries_the_render_count_across_builds(self, _name, signing_keys) -> None:
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart(f"c{i}", _TRENDS) for i in range(MAX_SLACK_REPORT_CHARTS)])
        budget = ChartRenderBudget(started=0.0)
        render, url = self._patched_render()
        with render as render_mock, url as url_mock, self.settings(SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS=signing_keys):
            render_mock.side_effect = lambda **kw: (MagicMock(id=render_mock.call_count), b"png")
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            build_scout_report_chart_blocks(
                report, run, delivery_id="delivery-rebuild", clock=lambda: 0.0, budget=budget
            )
            # The edit a rebuild reacts to: one chart's query changed, the other two did not.
            report.charts = [
                _chart("c0", {**_TRENDS, "source": {"kind": "TrendsQuery", "series": [{"event": "x"}]}}),
                *report.charts[1:],
            ]
            report.save(update_fields=["charts"])
            rebuilt = build_scout_report_chart_blocks(
                report, run, delivery_id="delivery-rebuild", clock=lambda: 0.0, budget=budget
            )

        # A rebuild shares the delivery's render allowance, so the whole delivery launches at most
        # MAX_SLACK_REPORT_CHARTS export workflows. The changed chart is dropped for want of a render;
        # the unchanged ones still show, reused from the delivery's own renders.
        assert render_mock.call_count == MAX_SLACK_REPORT_CHARTS
        assert [b["image_url"] for b in rebuilt if b["type"] == "image"] == ["https://img/2", "https://img/3"]

    def test_each_render_is_cached_before_the_next_starts(self) -> None:
        # The delivery task acks late, so a worker lost between two renders must leave the first one
        # behind for the retry to reuse, rather than only what a completed loop would have written.
        get_client().flushdb()
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS), _chart("b", _TRENDS)])
        cached_before_second_render: list[int] = []
        render, url = self._patched_render()

        def _render(**kw):
            if render_mock.call_count == 2:
                raw = get_client().get(_rendered_assets_cache_key("delivery-wt"))
                assert raw is not None
                cached_before_second_render.extend(v[0] for v in json.loads(raw).values())
            return (MagicMock(id=render_mock.call_count), b"png")

        with render as render_mock, url as url_mock:
            render_mock.side_effect = _render
            url_mock.side_effect = lambda **kw: f"https://img/{kw['asset_id']}"
            build_scout_report_chart_blocks(report, run, delivery_id="delivery-wt")

        assert cached_before_second_render == [1]

    def test_cache_outage_still_delivers_charts(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS)])
        render, url = self._patched_render()
        with (
            render as render_mock,
            url as url_mock,
            patch(
                "products.signals.backend.scout_harness.slack_charts.get_client",
                side_effect=ConnectionError("redis down"),
            ),
        ):
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.return_value = "https://img/1"
            blocks = build_scout_report_chart_blocks(report, run, delivery_id="delivery-2")

        assert [b["image_url"] for b in blocks if b["type"] == "image"] == ["https://img/1"]

    def test_render_budget_reserves_time_for_a_whole_render(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("a", _TRENDS), _chart("b", _TRENDS)])
        # The second chart is checked with less than one RENDER_TIMEOUT of budget left.
        clock = iter([0.0, 0.0, SLACK_REPORT_CHART_RENDER_BUDGET_SECONDS - RENDER_TIMEOUT.total_seconds() + 1])
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.return_value = "https://img/1"
            blocks = build_scout_report_chart_blocks(report, run, clock=lambda: next(clock))

        assert render_mock.call_count == 1
        assert len([b for b in blocks if b["type"] == "image"]) == 1

    @parameterized.expand(["_acting_user", "_chart_blocks"])
    def test_a_failure_outside_the_render_costs_the_charts_not_the_report(self, failing) -> None:
        # Everything the build does is best effort, not only the render itself: an exception escaping
        # here would fail the delivery task, which retries and then drops a report that used to post.
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("trend", _TRENDS)])
        render, url = self._patched_render()
        with (
            render as render_mock,
            url as url_mock,
            patch(
                f"products.signals.backend.scout_harness.slack_charts.{failing}",
                side_effect=RuntimeError("boom"),
            ),
        ):
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.return_value = "https://img/1"
            blocks, _ = build_scout_report_slack_message(report, run)

        assert [b["type"] for b in blocks] == ["context", "header", "section", "actions"]

    def test_report_message_places_charts_between_prose_and_link(self) -> None:
        run = self._make_run(created_by=self.user)
        report = self._make_report([_chart("trend", _TRENDS)], summary="Look at [signups](chart:trend).")
        render, url = self._patched_render()
        with render as render_mock, url as url_mock:
            render_mock.return_value = (MagicMock(id=1), b"png")
            url_mock.return_value = "https://img/1"
            blocks, _ = build_scout_report_slack_message(report, run)

        assert [b["type"] for b in blocks] == ["context", "header", "section", "section", "image", "actions"]
        assert blocks[2]["text"]["text"] == "Look at signups."
