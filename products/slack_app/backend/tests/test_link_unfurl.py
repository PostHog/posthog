import io
import json
from urllib.parse import quote, urlparse

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from parameterized import parameterized
from PIL import Image
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import Block
from slack_sdk.web.slack_response import SlackResponse
from structlog.testing import capture_logs

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.comment import Comment
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.models.user_integration import UserIntegration
from posthog.object_tags.kinds import ObjectRef
from posthog.storage import object_storage

from products.access_control.backend.models.access_control import AccessControl
from products.canvas.backend.facade import testing as canvas_testing
from products.cohorts.backend.models.cohort import Cohort
from products.conversations.backend.models.ticket import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.error_tracking.backend.facade import testing as error_tracking_testing
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.models import SignalReport
from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, route_posthog_code_event_to_relevant_region
from products.slack_app.backend.models import SlackChannel, SlackThreadTaskMapping
from products.slack_app.backend.services.slack_auth import write_auth_state_ok
from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES
from products.slack_app.backend.slack_link_unfurl import (
    _card_blocks,
    _date_range,
    _flag_chart,
    _insight_resource_label,
    _question_list,
    _tile_grid,
    _UnfurlCard,
    handle_posthog_link_unfurl,
    parse_posthog_resource_link,
)
from products.slack_app.backend.tasks import add_slack_unfurl_artifact_image, start_slack_unfurl_charts
from products.surveys.backend.models import Survey
from products.tasks.backend.models import Channel, Task, TaskRun

_TASK_ID = "c76f58f4-4c64-4cd7-825d-4ef89f6dd4ac"
_CHANNEL_ID = "0192f0a0-0000-4000-8000-000000000001"
_CANVAS_ID = "0192f0a0-0000-4000-8000-000000000002"
_RUN_ID = "0192f0a0-0000-4000-8000-000000000003"


def _create_task_artifact(
    team: Team,
    user: User,
    run_state: dict | None = None,
    project_id: int | None = None,
    name: str = "report.md",
    content_type: str = "text/markdown",
    artifacts_tab_link: bool = False,
) -> str:
    task = Task.objects.create(
        team=team,
        created_by=user,
        title="Fix checkout",
        description="",
        origin_product=Task.OriginProduct.USER_CREATED,
    )
    run = TaskRun.objects.create(
        task=task,
        team=team,
        state=run_state or {},
        artifacts=[
            {
                "id": "file-1",
                "name": name,
                "type": "artifact",
                "size": 2048,
                "content_type": content_type,
                "storage_path": f"tasks/artifacts/run_1/file-1_{name}",
                "uploaded_at": "2026-10-01T12:00:00+00:00",
            }
        ],
    )
    project = project_id or team.pk
    if artifacts_tab_link:
        return f"http://testserver/project/{project}/ai?task={task.id}&artifact={name}"
    return f"http://testserver/api/projects/{project}/tasks/{task.id}/runs/{run.id}/artifacts/file-1/download/"


class TestParsePosthogResourceLink:
    @parameterized.expand(
        [
            ("project_insight", "https://us.posthog.com/project/42/insights/abc123", "insight", "abc123"),
            ("insight_subpath", "https://eu.posthog.com/project/42/insights/abc123/edit", "insight", "abc123"),
            ("short_insight", "https://app.posthog.com/i/xyz789", "insight", "xyz789"),
            ("bi_worksheet", "https://us.posthog.com/project/42/bi/xyz789", "insight", "xyz789"),
            ("dashboard", "https://us.posthog.com/project/3/dashboard/99", "dashboard", "99"),
            ("ticket", "https://us.posthog.com/project/42/support/tickets/123", "ticket", "123"),
            (
                "ticket_fragment",
                "https://app.posthog.com/support/tickets/abc-uuid#panel=discussion",
                "ticket",
                "abc-uuid",
            ),
            ("task", f"https://us.posthog.com/project/42/tasks/{_TASK_ID}", "task", _TASK_ID),
            ("desktop_task", f"https://us.posthog.com/code/task/{_TASK_ID}", "task", _TASK_ID),
            ("space_task", f"https://us.posthog.com/code/channel/{_CHANNEL_ID}/tasks/{_TASK_ID}", "task", _TASK_ID),
            ("ai_task", f"https://us.posthog.com/project/42/ai?task={_TASK_ID}", "task", _TASK_ID),
            (
                "task_artifact",
                f"https://us.posthog.com/api/projects/42/tasks/{_TASK_ID}/runs/{_RUN_ID}/artifacts/file-1/download/",
                "task_artifact",
                "file-1",
            ),
            (
                "task_artifacts_tab",
                f"https://us.posthog.com/project/42/ai?task={_TASK_ID}&artifact=report.md",
                "task_artifact",
                "report.md",
            ),
            (
                "task_artifacts_tab_version",
                f"https://us.posthog.com/project/42/ai?task={_TASK_ID}&artifact=report.md&artifact_version=file-1",
                "task_artifact",
                "file-1",
            ),
            ("canvas", f"https://us.posthog.com/project/42/canvases/{_CANVAS_ID}", "canvas", _CANVAS_ID),
            ("desktop_canvas", f"https://us.posthog.com/code/canvas/{_CHANNEL_ID}/{_CANVAS_ID}", "canvas", _CANVAS_ID),
            ("notebook", "https://us.posthog.com/project/42/notebooks/Xy12", "notebook", "Xy12"),
            ("flag", "https://us.posthog.com/project/42/feature_flags/412", "flag", "412"),
            ("inbox_report", f"https://us.posthog.com/project/42/inbox/reports/{_TASK_ID}", "report", _TASK_ID),
            ("insight_new", "https://x.com/project/1/insights/new", None, None),
            (
                "adhoc_insight",
                "https://x.com/project/1/insights/new#q=%7B%22kind%22%3A%22InsightVizNode%22%7D",
                "adhoc_insight",
                "new",
            ),
            ("adhoc_broken_query", "https://x.com/project/1/insights/new#q=%7Bnot-json", None, None),
            ("adhoc_query_not_an_object", "https://x.com/project/1/insights/new#q=%5B1%5D", None, None),
            ("ticket_new", "https://x.com/support/tickets/new", None, None),
            ("flag_by_key", "https://us.posthog.com/project/42/feature_flags/my-flag", None, None),
            ("replay", "https://us.posthog.com/project/42/replay/0192f0a0", None, None),
            ("opted_out", "https://us.posthog.com/project/42/insights/abc123?unfurl=false", None, None),
            ("unrelated", "https://example.com/foo", None, None),
        ]
    )
    def test_parse(self, _name: str, url: str, kind: str | None, object_id: str | None) -> None:
        expected = ObjectRef(kind=kind, id=object_id) if kind and object_id else None
        assert parse_posthog_resource_link(url) == expected


class TestInsightResourceLabel:
    def test_insight_viz_trends(self):
        insight = Insight(
            team_id=1,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
        )
        assert _insight_resource_label(insight) == "Trends insight"

    def test_insight_viz_journeys(self) -> None:
        # Guards the user-facing name: without the map entry this would leak "PathsV2 insight".
        insight = Insight(
            team_id=1,
            query={"kind": "InsightVizNode", "source": {"kind": "PathsV2Query"}},
        )
        assert _insight_resource_label(insight) == "Journeys insight"

    def test_data_viz_sql(self):
        insight = Insight(
            team_id=1,
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        assert _insight_resource_label(insight) == "SQL insight"

    def test_legacy_filters(self):
        insight = Insight(team_id=1, filters={"insight": "FUNNELS"})
        assert _insight_resource_label(insight) == "Funnel insight"

    def test_fallback(self):
        insight = Insight(team_id=1)
        assert _insight_resource_label(insight) == "Insight"


class TestCardText:
    @parameterized.expand([("full", False), ("compact", True)])
    def test_card_blocks_stay_within_slack_text_limits(self, _name: str, compact: bool) -> None:
        card = _UnfurlCard(label="Insight", title="T" * 5000, details=("D" * 5000,))
        url = "https://us.posthog.com/project/2/insights/abc123?dashboard=1#q=" + "x" * 5000

        blocks = _card_blocks(card, kind="insight", url=url, compact=compact)

        texts = [block["text"]["text"] for block in blocks if "text" in block]
        texts += [element["text"] for block in blocks if block["type"] == "context" for element in block["elements"]]
        links = [element["url"] for block in blocks if block["type"] == "actions" for element in block["elements"]]
        assert all(len(text) <= 3000 for text in texts)
        assert "/insights/abc123?dashboard=1&utm_source=slack" in texts[0]
        assert all(len(link) <= 3000 and "/insights/abc123" in link for link in links)

    @parameterized.expand(
        [
            (
                "simple_rollout",
                {"groups": [{"properties": [], "rollout_percentage": 25}]},
                ["Rollout  █████░░░░░░░░░░░░░░░  25% of users"],
            ),
            (
                "multivariate",
                {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                },
                [
                    "Rollout  ████████████████████  100% of users",
                    "control  ██████████░░░░░░░░░░  50%",
                    "test     ██████████░░░░░░░░░░  50%",
                ],
            ),
            ("conditions_only", {"groups": [{"properties": [{"key": "email"}], "rollout_percentage": 50}]}, None),
        ]
    )
    def test_chart(self, _name: str, filters: dict, expected_lines: list[str] | None) -> None:
        chart = _flag_chart(filters["groups"], filters.get("multivariate", {}).get("variants", []))
        assert (chart.splitlines() if chart else None) == expected_lines

    @parameterized.expand(
        [
            (
                "odd_count",
                ["Signups", "Activation", "Revenue"],
                ["▪ Signups                  ▪ Activation", "▪ Revenue"],
            ),
            (
                "more_than_shown",
                [f"Tile {index}" for index in range(8)],
                "+ 2 more",
            ),
            ("empty", [], None),
        ]
    )
    def test_tile_grid(self, _name: str, names: list[str], expected: list[str] | str | None) -> None:
        grid = _tile_grid(names)
        if isinstance(expected, str):
            assert grid is not None and grid.splitlines()[-1] == expected
        else:
            assert (grid.splitlines() if grid else None) == expected

    @parameterized.expand(
        [
            ("relative_days", "-30d", "Last 30 days"),
            ("single_month", "-1m", "Last month"),
            ("named", "mStart", "This month"),
            ("absolute_date", "2026-01-01", None),
            ("missing", None, None),
        ]
    )
    def test_date_range(self, _name: str, date_from: str | None, expected: str | None) -> None:
        query = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "dateRange": {"date_from": date_from}}}
        assert _date_range(query) == expected

    def test_question_list_numbers_and_caps_questions(self) -> None:
        questions = [{"question": f"Question {index}"} for index in range(7)]
        assert _question_list(questions) == "1. Question 0\n2. Question 1\n3. Question 2\n+ 4 more"


@pytest.mark.django_db
class TestHandlePosthogLinkUnfurl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="TSlack01",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.insight = Insight.objects.create(
            team=self.team,
            short_id="insight1",
            name="Weekly active users",
            description="A test description",
            saved=True,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
        )

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_insight_when_user_resolved(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        site = "http://testserver"
        url = f"{site}/project/{self.team.pk}/insights/{self.insight.short_id}"

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url, "domain": "testserver"}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        call_kw = mock_client.chat_unfurl.call_args.kwargs
        assert url in call_kw["unfurls"]
        text = self._unfurl_text(call_kw["unfurls"][url])
        assert "Trends insight" in text
        assert "Weekly active users" in text
        assert "A test description" in text
        actions = next(block for block in call_kw["unfurls"][url]["blocks"] if block["type"] == "actions")
        assert actions["elements"][0]["url"] == f"{url}?utm_source=slack&utm_medium=unfurl&utm_content=insight"

    @parameterized.expand(
        [
            ("allowed", True, True),
            ("public_sharing_off", False, False),
        ]
    )
    @patch("products.slack_app.backend.tasks.start_slack_unfurl_charts.delay")
    @patch("products.slack_app.backend.slack_link_unfurl.sync_connect")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_insight_unfurl_starts_the_chart_workflow_only_when_allowed(
        self,
        _name: str,
        public_sharing: bool,
        expect_started: bool,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
        mock_sync_connect: MagicMock,
        mock_delay: MagicMock,
    ) -> None:
        # Runs the queued task in process, through JSON like the Celery broker.
        mock_delay.side_effect = lambda **kwargs: start_slack_unfurl_charts(**json.loads(json.dumps(kwargs)))
        self.organization.allow_publicly_shared_resources = public_sharing
        self.organization.save()
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_sync_connect.return_value.start_workflow = AsyncMock()
        url = f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"

        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        start_workflow = mock_sync_connect.return_value.start_workflow
        if not expect_started:
            start_workflow.assert_not_called()
            return
        inputs = start_workflow.call_args.args[1]
        assert [chart.insight_id for chart in inputs.charts] == [self.insight.id]
        assert (
            inputs.unfurls == mock_slack_integration_class.return_value.client.chat_unfurl.call_args.kwargs["unfurls"]
        )

    @parameterized.expand([("query_access", True), ("no_query_access", False)])
    @patch("products.slack_app.backend.tasks.start_slack_unfurl_charts.delay")
    @patch("products.slack_app.backend.slack_link_unfurl.sync_connect")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_adhoc_insight_link_posts_no_card_and_queues_its_chart(
        self,
        _name: str,
        query_access: bool,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
        mock_sync_connect: MagicMock,
        mock_delay: MagicMock,
    ) -> None:
        mock_delay.side_effect = lambda **kwargs: start_slack_unfurl_charts(**json.loads(json.dumps(kwargs)))
        if not query_access:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(resource="query", team=self.team, access_level="none")
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_sync_connect.return_value.start_workflow = AsyncMock()
        query = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}
        url = f"http://testserver/project/{self.team.pk}/insights/new#q={quote(json.dumps(query))}"

        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        mock_slack_integration_class.return_value.client.chat_unfurl.assert_not_called()
        start_workflow = mock_sync_connect.return_value.start_workflow
        if not query_access:
            start_workflow.assert_not_called()
            return
        inputs = start_workflow.call_args.args[1]
        assert [chart.query for chart in inputs.charts] == [query]
        blocks = inputs.unfurls[url]["blocks"]
        assert "Unsaved insight" in blocks[0]["text"]["text"]
        assert "Trends insight" in blocks[1]["elements"][0]["text"]

    @patch("products.slack_app.backend.tasks.start_slack_unfurl_charts.delay")
    @patch("products.slack_app.backend.slack_link_unfurl.sync_connect")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_adhoc_link_beside_another_link_is_not_unfurled(
        self,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
        mock_sync_connect: MagicMock,
        mock_delay: MagicMock,
    ) -> None:
        mock_delay.side_effect = lambda **kwargs: start_slack_unfurl_charts(**json.loads(json.dumps(kwargs)))
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_sync_connect.return_value.start_workflow = AsyncMock()
        base = f"http://testserver/project/{self.team.pk}"
        saved = f"{base}/insights/{self.insight.short_id}"
        adhoc = (
            f"{base}/insights/new#q={quote(json.dumps({'kind': 'InsightVizNode', 'source': {'kind': 'TrendsQuery'}}))}"
        )

        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": saved}, {"url": adhoc}]},
            self.integration,
        )

        assert list(mock_slack_integration_class.return_value.client.chat_unfurl.call_args.kwargs["unfurls"]) == [saved]
        inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert [chart.url for chart in inputs.charts] == [saved]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_task_and_attaches_public_thread_once(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Review <https://example.com|Slack task links>",
            description="Sensitive prompt that must not appear",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id="U_OWNER",
            config={"slack_team_id": self.integration.integration_id},
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_client.conversations_info.return_value = {
            "channel": {"is_channel": True, "is_private": False, "is_shared": False}
        }
        mock_client.users_info.return_value = {
            "user": {"deleted": False, "is_restricted": False, "is_ultra_restricted": False}
        }
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/tasks/{task.id}"
        event = {
            "channel": "C_PUBLIC",
            "message_ts": "123.456",
            "thread_ts": "120.000",
            "user": "U_SHARER",
            "source": "conversations_history",
            "links": [{"url": url}],
        }

        handle_posthog_link_unfurl(event, self.integration)
        handle_posthog_link_unfurl(event, self.integration)

        text = mock_client.chat_unfurl.call_args.kwargs["unfurls"][url]["blocks"][0]["text"]["text"]
        assert "Review &lt;https://example.com|Slack task links&gt;" in text
        assert "<https://example.com|Slack task links>" not in text
        assert "Sensitive prompt" not in text
        mock_client.conversations_info.assert_called_once_with(channel="C_PUBLIC")
        mock_client.users_info.assert_called_once_with(user="U_OWNER")
        task.refresh_from_db()
        state = task.state or {}
        references = state.get("slack_thread_references")
        assert isinstance(references, list)
        assert references == [
            {
                "slack_workspace_id": self.integration.integration_id,
                "channel": "C_PUBLIC",
                "thread_ts": "120.000",
                "shared_by_slack_user_id": "U_SHARER",
                "created_at": references[0]["created_at"],
            }
        ]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_private_channel_unfurls_task_without_attaching_reference(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Private discussion",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_client.conversations_info.return_value = {"channel": {"is_channel": True, "is_private": True}}
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/tasks/{task.id}"

        handle_posthog_link_unfurl(
            {
                "channel": "C_PRIVATE",
                "message_ts": "123.456",
                "user": "U_OWNER",
                "source": "conversations_history",
                "links": [{"url": url}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        task.refresh_from_db()
        assert "slack_thread_references" not in (task.state or {})

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_when_user_not_resolved(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        mock_resolve.return_value = None
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_not_called()

    @parameterized.expand(
        [
            # (event author, run told to link, thread has a run, author resolved)
            ("placeholder_linking_run", "U00", True, True, "U_ACTOR"),
            ("placeholder_run_not_told_to_link", "U00", False, True, "U00"),
            ("placeholder_no_run_in_thread", "U00", True, False, "U00"),
            ("our_bot_linking_run", "U_OUR_BOT", True, True, "U_ACTOR"),
            ("our_bot_no_run_in_thread", "U_OUR_BOT", True, False, "U_OUR_BOT"),
        ]
    )
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_bot_reply_link_unfurls_for_the_thread_actor(
        self,
        _name: str,
        author: str,
        run_links: bool,
        has_run: bool,
        expected_resolved: str,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        # Slack credits a bot-posted message to our bot user or to a placeholder author, and neither
        # resolves to a PostHog user, so without this path a chart link in the agent's answer never
        # unfurls. The attribution stays narrow: a thread whose run was told to share links, and the
        # actor is the one the run recorded rather than the mapping's stale column.
        write_auth_state_ok(self.integration.id, bot_user_id="U_OUR_BOT")
        mock_resolve.side_effect = lambda _slack, _integration, uid, *_a, **_k: (
            MagicMock(user=self.user) if uid == "U_ACTOR" else None
        )
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client
        if has_run:
            task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Chart the signups",
                description="",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            run = TaskRun.objects.create(
                task=task,
                team=self.team,
                state={"slack_chart_links": run_links, "slack_actor_slack_user_id": "U_ACTOR"},
            )
            SlackThreadTaskMapping.objects.create(
                team=self.team,
                integration=self.integration,
                slack_workspace_id=self.integration.integration_id,
                channel="C1",
                thread_ts="100.000",
                task=task,
                task_run=run,
                mentioning_slack_user_id="U_ASKER",
                latest_actor_slack_user_id="U_STALE",
            )
        url = f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "thread_ts": "100.000",
                "user": author,
                "links": [{"url": url}],
            },
            self.integration,
        )

        assert mock_resolve.call_args.args[2] == expected_resolved
        assert mock_client.chat_unfurl.called == (expected_resolved == "U_ACTOR")

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def test_skips_a_link_belonging_to_the_other_region(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        # Resource ids repeat across regions, so resolving an eu.posthog.com link here would unfurl
        # whichever local insight happens to carry the same short id — a card of the wrong data
        # attached to someone else's link.
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"https://eu.posthog.com/project/{self.team.pk}/insights/{self.insight.short_id}"
        with capture_logs() as logs:
            handle_posthog_link_unfurl(
                {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": url}]},
                self.integration,
            )

        mock_client.chat_unfurl.assert_not_called()
        result = next(log for log in logs if log["event"] == "slack_app_link_unfurl_result")
        assert result["skipped"] == [{"kind": "insight", "ref": self.insight.short_id, "reason": "other_region"}]

    def _make_bot_ready(self) -> None:
        self.integration.config = {"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))}
        self.integration.save()

    def _unfurl_links(self, urls: list[str], channel: str = "C1") -> None:
        handle_posthog_link_unfurl(
            {
                "channel": channel,
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url, "domain": "testserver"} for url in urls],
            },
            self.integration,
        )

    @staticmethod
    def _invite_blocks(mock_client: MagicMock) -> list[dict]:
        blocks = [
            block
            for payload in mock_client.chat_unfurl.call_args.kwargs["unfurls"].values()
            for block in payload["blocks"]
        ]
        return [block for block in blocks if block["type"] == "context" and "@PostHog" in block["elements"][0]["text"]]

    @parameterized.expand([("ai_approved", True, 1), ("ai_not_approved", False, 0)])
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurl_invites_a_follow_up_only_when_the_org_approved_ai(
        self,
        _name: str,
        ai_approved: bool,
        expected_invites: int,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()
        self._make_bot_ready()
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links([f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"])

        invites = self._invite_blocks(mock_client)
        assert len(invites) == expected_invites
        if expected_invites:
            assert "dig into this insight" in invites[0]["elements"][0]["text"]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurl_invite_offers_setup_when_the_install_cannot_be_mentioned(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        # An install predating app_mentions:read can unfurl but not answer, so inviting a mention
        # would point at a bot that stays silent.
        self.integration.config = {"scope": "links:read,chat:write"}
        self.integration.save()
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links([f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"])

        text = self._invite_blocks(mock_client)[0]["elements"][0]["text"]
        assert "Set up the @PostHog bot" in text
        assert "about this insight here" in text
        assert "mention" not in text

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurl_invite_appears_once_per_channel_per_day(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        self._make_bot_ready()
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"

        self._unfurl_links([url])
        assert len(self._invite_blocks(mock_client)) == 1

        self._unfurl_links([url])
        assert self._invite_blocks(mock_client) == []

        self._unfurl_links([url], channel="C2")
        assert len(self._invite_blocks(mock_client)) == 1

    @patch("products.slack_app.backend.slack_link_unfurl.get_client")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurl_still_sent_when_redis_is_unreachable(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock, mock_get_client: MagicMock
    ) -> None:
        self._make_bot_ready()
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client
        mock_get_client.side_effect = ImproperlyConfigured("Redis not configured!")

        self._unfurl_links([f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"])

        assert len(mock_client.chat_unfurl.call_args.kwargs["unfurls"]) == 1
        assert self._invite_blocks(mock_client) == []

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_message_with_several_links_carries_one_invite(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        self._make_bot_ready()
        dashboard = Dashboard.objects.create(team=self.team, name="Growth")
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links(
            [
                f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}",
                f"http://testserver/project/{self.team.pk}/dashboard/{dashboard.pk}",
            ],
        )

        unfurls = mock_client.chat_unfurl.call_args.kwargs["unfurls"]
        assert len(unfurls) == 2
        for unfurl in unfurls.values():
            self._assert_slack_accepts(unfurl)
        assert not [block for payload in unfurls.values() for block in payload["blocks"] if block["type"] == "actions"]
        assert len(self._invite_blocks(mock_client)) == 1

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_reports_why_recognized_links_were_not_unfurled(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        # Every reason to skip a link used to be a bare `continue`, so "no unfurl appeared" was
        # indistinguishable from "Slack never delivered the event" once it reached production.
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_slack_integration_class.return_value.client = MagicMock()

        with capture_logs() as logs:
            handle_posthog_link_unfurl(
                {
                    "channel": "C1",
                    "message_ts": "123.456",
                    "user": "U1",
                    "links": [
                        {"url": f"http://testserver/project/{self.team.pk}/insights/nosuchid"},
                        {"url": f"http://testserver/project/{self.team.pk}/dashboard/424242"},
                        {"url": "https://example.com/somewhere-else"},
                        {"url": f"http://testserver/project/{self.team.pk}/sql?open_query=SELECT%20secret"},
                    ],
                },
                self.integration,
            )

        mock_slack_integration_class.return_value.client.chat_unfurl.assert_not_called()
        result = next(log for log in logs if log["event"] == "slack_app_link_unfurl_result")
        assert result["unfurled"] == 0
        assert result["skipped"] == [
            {"kind": "insight", "ref": "nosuchid", "reason": "not_found"},
            {"kind": "dashboard", "ref": "424242", "reason": "not_found"},
            {"kind": "hogql", "reason": "unsupported"},
        ]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_insight_when_project_segment_mismatched(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """Project id in the URL is ignored; lookup uses the connected team + short_id only."""
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/project/99999/insights/{self.insight.short_id}"
        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        assert url in mock_client.chat_unfurl.call_args.kwargs["unfurls"]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_dashboard(self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Main board", description="Overview")
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        site = "http://testserver"
        url = f"{site}/project/{self.team.pk}/dashboard/{dashboard.pk}"

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "Dashboard" in text
        assert "Main board" in text

    def _create_object(self, kind: str) -> tuple[str, list[str]]:
        base = f"http://testserver/project/{self.team.pk}"
        match kind:
            case "canvas":
                with team_scope(self.team.pk):
                    channel = Channel.objects.create(team=self.team, name="Growth")
                canvas_id = canvas_testing.create_canvas(
                    team_id=self.team.pk, channel_id=channel.id, name="Launch board", created_by_id=self.user.id
                )
                return f"{base}/canvases/{canvas_id}", ["Launch board", "Space: Growth"]
            case "notebook":
                notebook = Notebook.objects.create(
                    team=self.team, title="Activation dip", text_content="Activation fell", created_by=self.user
                )
                return f"{base}/notebooks/{notebook.short_id}", ["Activation dip", "Activation fell"]
            case "flag":
                flag = FeatureFlag.objects.create(
                    team=self.team,
                    key="new-checkout",
                    created_by=self.user,
                    filters={"groups": [{"properties": [], "rollout_percentage": 25}]},
                )
                return f"{base}/feature_flags/{flag.pk}", ["new-checkout", "*Active*", "25% of users"]
            case "experiment":
                flag = FeatureFlag.objects.create(team=self.team, key="button-color", created_by=self.user)
                experiment = Experiment.objects.create(team=self.team, name="Button color", feature_flag=flag)
                return f"{base}/experiments/{experiment.pk}", ["Button color", "*Draft*"]
            case "survey":
                survey = Survey.objects.create(
                    team=self.team,
                    name="Checkout NPS",
                    type="popover",
                    questions=[{"type": "open", "question": "Why?"}],
                )
                return f"{base}/surveys/{survey.pk}", ["Checkout NPS", "*Draft*", "1 question", "1. Why?"]
            case "cohort":
                cohort = Cohort.objects.create(team=self.team, name="Power users", count=1200)
                return f"{base}/cohorts/{cohort.pk}", ["Power users", "1,200 persons"]
            case "error":
                issue_id = error_tracking_testing.create_issue(
                    team_id=self.team.pk, name="TypeError", description="Cannot read id"
                )
                return f"{base}/error_tracking/{issue_id}", ["TypeError", "*Active*", "Cannot read id"]
            case "task":
                task = Task.objects.create(
                    team=self.team,
                    created_by=self.user,
                    title="Fix checkout",
                    description="",
                    origin_product=Task.OriginProduct.USER_CREATED,
                )
                TaskRun.objects.create(
                    task=task,
                    team=self.team,
                    status=TaskRun.Status.COMPLETED,
                    output={"pr_url": "https://github.com/example/repo/pull/7"},
                )
                return f"http://testserver/code/task/{task.id}", [
                    "Fix checkout",
                    "*Completed*",
                    "View pull request",
                ]
            case "task_artifacts_tab":
                return _create_task_artifact(self.team, self.user, artifacts_tab_link=True), [
                    "report.md",
                    "Task: Fix checkout",
                    "artifact_version=file-1",
                    "Download",
                ]
            case "task_artifact":
                return _create_task_artifact(self.team, self.user), [
                    "report.md",
                    "2.0 KB",
                    "Task: Fix checkout",
                    "/ai?task=",
                    "artifact=report.md",
                    "Download",
                ]
            case "report":
                report = SignalReport.objects.create(
                    team=self.team,
                    title="Checkout drop",
                    summary="Fewer orders",
                    status=SignalReport.Status.IN_PROGRESS,
                )
                return f"{base}/inbox/reports/{report.pk}", [
                    "Checkout drop",
                    "*In progress*",
                    "0 signals",
                    "/static/icons/self-driving.png",
                ]
        raise ValueError(kind)

    @parameterized.expand([("deactivated", "user"), ("task_access_removed", "access_control")])
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_artifact_image_job_rechecks_access(
        self, _name: str, revoke: str, mock_slack_integration_class: MagicMock
    ) -> None:
        url = _create_task_artifact(self.team, self.user, name="chart.png", content_type="image/png")
        member = User.objects.create_and_join(self.organization, "member@posthog.com", "password")
        Task.objects.filter(team=self.team).update(created_by=member)
        if revoke == "user":
            member.is_active = False
            member.save()
        else:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(resource="task", team=self.team, access_level="none")

        with patch("posthog.storage.object_storage.read_bytes") as mock_read_bytes:
            add_slack_unfurl_artifact_image(
                team_id=self.team.pk,
                integration_id=self.integration.id,
                user_id=member.pk,
                event={"channel": "C1", "message_ts": "123.456", "user": "U1"},
                unfurls={url: {"blocks": []}},
                url=url,
                title="chart.png",
            )

        mock_read_bytes.assert_not_called()
        mock_slack_integration_class.return_value.client.chat_unfurl.assert_not_called()

    @parameterized.expand(
        [
            ("task_hidden_from_sharer", None, None, True),
            ("run_with_analytics_context", {"analytics_query_context": {"kind": "metric"}}, None, False),
            ("other_project", None, 999999, False),
        ]
    )
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_task_artifact_the_sharer_cannot_download(
        self,
        _name: str,
        run_state: dict | None,
        project_id: int | None,
        shared_by_other_member: bool,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        url = _create_task_artifact(self.team, self.user, run_state, project_id)
        sharer = (
            User.objects.create_and_join(self.organization, "other-member@posthog.com", "password")
            if shared_by_other_member
            else self.user
        )
        mock_resolve.return_value = MagicMock(user=sharer)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links([url])

        mock_client.chat_unfurl.assert_not_called()

    @parameterized.expand(
        [
            (kind,)
            for kind in (
                "canvas",
                "notebook",
                "flag",
                "experiment",
                "survey",
                "cohort",
                "error",
                "report",
                "task",
                "task_artifact",
                "task_artifacts_tab",
            )
        ]
    )
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_kind(self, kind: str, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock) -> None:
        url, expected = self._create_object(kind)
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links([url])

        unfurl = mock_client.chat_unfurl.call_args.kwargs["unfurls"][url]
        self._assert_slack_accepts(unfurl)
        text = self._unfurl_text(unfurl)
        for snippet in expected:
            assert snippet in text

    @parameterized.expand(
        [
            ("notebook", "notebook"),
            ("flag", "feature_flag"),
            ("experiment", "experiment"),
            ("survey", "survey"),
            ("cohort", "cohort"),
            ("error", "error_tracking"),
            ("report", "task"),
            ("task", "task"),
            ("task_artifact", "task"),
        ]
    )
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_kind_without_viewer_access(
        self, kind: str, resource: str, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, f"restricted-{kind}@posthog.com", "password")
        url, _ = self._create_object(kind)
        AccessControl.objects.create(resource=resource, team=self.team, access_level="none")
        mock_resolve.return_value = MagicMock(user=member)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        self._unfurl_links([url])

        mock_client.chat_unfurl.assert_not_called()

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_dashboard_card_lists_only_insights_the_sharer_can_view(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "dashboard-viewer@posthog.com", "password")
        dashboard = Dashboard.objects.create(team=self.team, name="Growth review")
        visible = Insight.objects.create(team=self.team, name="Visible tile", saved=True)
        hidden = Insight.objects.create(team=self.team, name="Hidden tile", saved=True)
        DashboardTile.objects.create(dashboard=dashboard, insight=visible)
        DashboardTile.objects.create(dashboard=dashboard, insight=hidden)
        AccessControl.objects.create(
            team=self.team, resource="insight", resource_id=str(hidden.id), access_level="none"
        )
        mock_resolve.return_value = MagicMock(user=member)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/dashboard/{dashboard.pk}"

        self._unfurl_links([url])

        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "Visible tile" in text
        assert "1 insight" in text
        assert "Hidden tile" not in text

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_experiment_card_shows_a_paused_experiment_as_paused(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="paused-test", created_by=self.user, active=False)
        experiment = Experiment.objects.create(
            team=self.team, name="Paused test", feature_flag=flag, start_date=timezone.now(), status="running"
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/experiments/{experiment.pk}"

        self._unfurl_links([url])

        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "*Paused*" in text

    @staticmethod
    def _assert_slack_accepts(unfurl: dict) -> None:
        for block in unfurl["blocks"]:
            parsed = Block.parse(block)
            assert parsed is not None
            parsed.validate_json()

    @patch("products.slack_app.backend.slack_link_unfurl.capture_slack_event")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_rejected_card_falls_back_to_compact(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        rejection = SlackResponse(
            client=None,
            http_verb="POST",
            api_url="https://slack.com/api/chat.unfurl",
            req_args={},
            data={"ok": False, "error": "cannot_parse_attachment"},
            headers={},
            status_code=200,
        )
        mock_client.chat_unfurl.side_effect = [SlackApiError("rejected", rejection), None]
        mock_slack_integration_class.return_value.client = mock_client
        url = f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"

        self._unfurl_links([url])

        retried = mock_client.chat_unfurl.call_args.kwargs["unfurls"][url]["blocks"]
        assert mock_client.chat_unfurl.call_count == 2
        assert [block["type"] for block in retried if block["type"] != "context"] == ["section"]
        failure = next(c for c in mock_capture.call_args_list if c.args[1] == "slack app link unfurl failed")
        assert failure.kwargs["error"] == "cannot_parse_attachment"

    @staticmethod
    def _unfurl_text(unfurl: dict) -> str:
        parts: list[str] = []
        for block in unfurl["blocks"]:
            if block["type"] == "section":
                parts.extend(field["text"] for field in [block.get("text"), *block.get("fields", [])] if field)
            elif block["type"] == "context":
                parts.extend(element.get("text") or element["image_url"] for element in block["elements"])
            elif block["type"] == "actions":
                parts.extend(element["text"]["text"] for element in block["elements"])
        return "\n".join(parts)

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_ticket(self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock) -> None:
        ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="s1",
            distinct_id="d1",
            # Default display-name settings prefer email over name.
            anonymous_traits={"name": "John Doe", "email": "john@example.com"},
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/project/{self.team.pk}/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "Ticket #1" in text
        assert "Requested by john@example.com" in text
        assert "New" in text  # default status, humanized

    @parameterized.expand([("resource",), ("object",)])
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_ticket_without_viewer_access(
        self,
        denied_scope: str,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "restricted-unfurl@posthog.com", "password")
        ticket = Ticket.objects.create(team=self.team, ticket_number=5, widget_session_id="s5", distinct_id="d5")
        if denied_scope == "resource":
            AccessControl.objects.create(resource="ticket", team=self.team, access_level="none")
        else:
            AccessControl.objects.create(
                resource="ticket",
                resource_id=str(ticket.id),
                organization_member=member.organization_memberships.get(organization=self.organization),
                team=self.team,
                access_level="none",
            )
        mock_resolve.return_value = MagicMock(user=member)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/project/{self.team.pk}/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "1.2", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        mock_client.chat_unfurl.assert_not_called()

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_ticket_from_another_project(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        # ticket_number is per-project — a link naming a different project must not resolve to our #1.
        ticket = Ticket.objects.create(team=self.team, ticket_number=1, widget_session_id="s9", distinct_id="d9")
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/project/{self.team.pk + 1}/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "1.2", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        mock_client.chat_unfurl.assert_not_called()

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_ticket_requester_follows_display_name_setting(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        # A project that displays people by name should show the name, not the email.
        self.team.person_display_name_properties = ["name", "email"]
        self.team.save()
        ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=3,
            widget_session_id="s3",
            distinct_id="d3",
            anonymous_traits={"name": "John Doe", "email": "john@example.com"},
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "1.2", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "Requested by John Doe" in text

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_ticket_with_opening_message(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        ticket = Ticket.objects.create(team=self.team, ticket_number=2, widget_session_id="s2", distinct_id="d2")
        # bulk_create skips conversations' post_save signals — we only need the row for the lookup.
        Comment.objects.bulk_create(
            [
                Comment(
                    team=self.team, scope="conversations_ticket", item_id=str(ticket.id), content="App crashes on login"
                )
            ]
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "1.2", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "App crashes on login" in text

    @parameterized.expand(
        [
            ("private_note", {"item_context": {"is_private": True}}),
            ("soft_deleted", {"deleted": True}),
        ]
    )
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_ticket_hidden_opening_message_not_surfaced(
        self, _name: str, overrides: dict, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        ticket = Ticket.objects.create(team=self.team, ticket_number=4, widget_session_id="s4", distinct_id="d4")
        Comment.objects.bulk_create(
            [
                Comment(
                    team=self.team,
                    scope="conversations_ticket",
                    item_id=str(ticket.id),
                    content="internal only",
                    **overrides,
                )
            ]
        )
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/support/tickets/{ticket.ticket_number}"
        handle_posthog_link_unfurl(
            {"channel": "C1", "message_ts": "1.2", "user": "U1", "links": [{"url": url}]},
            self.integration,
        )

        text = self._unfurl_text(mock_client.chat_unfurl.call_args.kwargs["unfurls"][url])
        assert "internal only" not in text


# Kept apart from TestHandlePosthogLinkUnfurl: that class builds a TrendsQuery in setUp, and the
# model-crossing invariant counts it as run by any test in the class that calls the test client.
@pytest.mark.django_db
class TestTaskArtifactImageUnfurl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="TSlack01",
            sensitive_config={"access_token": "xoxb-test"},
        )

    @parameterized.expand(
        [
            ("png", "chart.png", "image/png", "PNG", True, True),
            ("jpeg_shown_as_png", "photo.jpg", "image/jpeg", "JPEG", True, True),
            ("cmyk_jpeg_shown_as_png", "print.jpg", "image/jpeg", "CMYK", True, True),
            ("bytes_are_not_an_image", "chart.png", "image/png", None, True, False),
            ("public_sharing_off", "chart.png", "image/png", "PNG", False, False),
            ("file_type_is_not_an_image", "report.md", "text/markdown", None, True, False),
        ]
    )
    @override_settings(SITE_URL="https://app.example.com", OBJECT_STORAGE_ENABLED=False)
    @patch("products.slack_app.backend.tasks.add_slack_unfurl_artifact_image.delay")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_task_artifact_image_shows_in_its_card(
        self,
        _name: str,
        name: str,
        content_type: str,
        image_format: str | None,
        public_sharing: bool,
        expect_image: bool,
        mock_slack_integration_class: MagicMock,
        mock_resolve: MagicMock,
        mock_delay: MagicMock,
    ) -> None:
        # Runs the queued task in process, through JSON like the Celery broker.
        mock_delay.side_effect = lambda **kwargs: add_slack_unfurl_artifact_image(**json.loads(json.dumps(kwargs)))
        self.organization.allow_publicly_shared_resources = public_sharing
        self.organization.save()
        content = b"<html>not an image</html>"
        if image_format:
            buffer = io.BytesIO()
            mode = "CMYK" if image_format == "CMYK" else "RGB"
            Image.new(mode, (4, 4)).save(buffer, format="JPEG" if image_format == "CMYK" else image_format)
            content = buffer.getvalue()
        url = _create_task_artifact(self.team, self.user, name=name, content_type=content_type)
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = mock_slack_integration_class.return_value.client
        read_bytes = object_storage.read_bytes

        with patch(
            "posthog.storage.object_storage.read_bytes",
            side_effect=lambda path, *args, **kwargs: (
                content if path.startswith("tasks/artifacts/") else read_bytes(path, *args, **kwargs)
            ),
        ):
            handle_posthog_link_unfurl(
                {"channel": "C1", "message_ts": "123.456", "user": "U1", "links": [{"url": url}]},
                self.integration,
            )

            if not expect_image:
                mock_client.chat_unfurl.assert_called_once()
                return
            unfurl = mock_client.chat_unfurl.call_args.kwargs["unfurls"][url]
            TestHandlePosthogLinkUnfurl._assert_slack_accepts(unfurl)
            types = [block["type"] for block in unfurl["blocks"]]
            assert types.index("image") == types.index("actions") - 1
            image_url = urlparse(unfurl["blocks"][types.index("image")]["image_url"])
            assert image_url.netloc == "app.example.com"
            self.client.logout()
            response = self.client.get(f"{image_url.path}?{image_url.query}")

        assert response.status_code == 200
        with Image.open(io.BytesIO(response.getvalue())) as served:
            assert served.format == "PNG"


@override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
class TestLinkUnfurlChannelGate(TestCase):
    SLACK_TEAM_ID = "TGate01"
    CHANNEL_ID = "C_EXT"

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Gate Org")
        self.team = Team.objects.create(organization=self.organization, name="Gate Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=self.SLACK_TEAM_ID,
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )
        # load_integrations calls auth.test on cache miss; pre-seed ok so the resolver short-circuits.
        write_auth_state_ok(self.integration.id, bot_user_id=None)

    def _event(self) -> dict:
        return {
            "type": "link_shared",
            "channel": self.CHANNEL_ID,
            "user": "U_SHARER",
            "message_ts": "1.2",
            "links": [{"url": "https://us.posthog.com/support/tickets/1"}],
        }

    def _route(self, *, is_ext_shared_channel: bool) -> str:
        request = self.factory.post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        return route_posthog_code_event_to_relevant_region(
            request, self._event(), self.SLACK_TEAM_ID, is_ext_shared_channel=is_ext_shared_channel
        )

    @parameterized.expand(
        [
            ("ext_unapproved", True, False, False),
            ("ext_approved", True, True, False),
            ("internal_channel", False, False, True),
        ]
    )
    @patch("products.slack_app.backend.api.handle_posthog_link_unfurl")
    def test_unfurl_never_reaches_an_external_channel(
        self, _name: str, is_ext_shared: bool, approved: bool, expect_unfurled: bool, mock_unfurl: MagicMock
    ) -> None:
        if approved:
            SlackChannel.objects.create(
                slack_workspace_id=self.SLACK_TEAM_ID,
                slack_channel_id=self.CHANNEL_ID,
                approved_at=timezone.now(),
            )

        result = self._route(is_ext_shared_channel=is_ext_shared)

        assert result == ROUTE_HANDLED_LOCALLY
        assert mock_unfurl.called is expect_unfurled
