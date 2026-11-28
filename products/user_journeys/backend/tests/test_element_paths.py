import re
from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import HogQLQueryResponse

from posthog.models import Element, Organization, Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.user_journeys.backend.facade.contracts import ElementClickStep, PageviewStep
from products.user_journeys.backend.facade.enums import UrlMatching
from products.user_journeys.backend.logic.element_paths import NodeKey, PathCleaning, node_from_key
from products.user_journeys.backend.presentation.element_paths_serializers import ElementPathsQuerySerializer

ANCHOR = ElementClickStep(selector="button.signup", text="Sign up")
NO_CLEANING = PathCleaning(aliases=())
FLAG = "products.user_journeys.backend.facade.api.is_user_journeys_enabled"
EXECUTE = "products.user_journeys.backend.logic.element_paths.execute_hogql_query"


def _pageview(path: str) -> NodeKey:
    return NodeKey(kind="pageview", path=path, tag="", element_id="", text="", href="")


def _click(tag: str = "", element_id: str = "", text: str = "", href: str = "") -> NodeKey:
    return NodeKey(kind="click", path="", tag=tag, element_id=element_id, text=text, href=href)


class TestElementPathNodes(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "plain_path",
                "/pricing",
                NO_CLEANING,
                True,
                [
                    "https://example.com/pricing",
                    "https://example.com/pricing/?plan=pro",
                    "https://example.com/pricing#faq",
                ],
                ["https://example.com/pricing-old", "https://example.com/en/pricing"],
            ),
            (
                "root",
                "/",
                NO_CLEANING,
                True,
                ["https://example.com", "https://example.com/?a=1"],
                ["https://example.com/a"],
            ),
            (
                "cleaned_path",
                "/project/<id>/insights",
                PathCleaning(aliases=("<id>",)),
                False,
                ["https://example.com/project/123/insights"],
                ["https://example.com/project/123/dashboards"],
            ),
        ]
    )
    def test_pageview_step_matches_the_urls_the_node_counts(
        self,
        _name: str,
        path: str,
        cleaning: PathCleaning,
        exact: bool,
        matching_urls: list[str],
        other_urls: list[str],
    ) -> None:
        node = node_from_key(_pageview(path), ANCHOR, cleaning)

        assert node.label == path
        assert node.step_is_exact is exact
        assert isinstance(node.step, PageviewStep)
        assert node.step.url_matching == UrlMatching.REGEX
        for url in matching_urls:
            assert re.search(node.step.url, url), url
        for url in other_urls:
            assert not re.search(node.step.url, url), url

    @parameterized.expand(
        [
            ("id", _click(tag="button", element_id="cta", text="Buy"), "#cta", "Buy", None, "Buy"),
            ("unsafe_id", _click(tag="span", element_id=":r1:", text="Go"), "span", "Go", None, "Go"),
            ("link", _click(tag="a", href="/docs"), "a", None, "/docs", "/docs"),
            ("long_text", _click(tag="p", text="x" * 500), "p", None, None, "x" * 400),
        ]
    )
    def test_click_step_comes_from_the_innermost_element(
        self,
        _name: str,
        key: NodeKey,
        selector: str,
        text: str | None,
        href: str | None,
        label: str,
    ) -> None:
        node = node_from_key(key, ANCHOR, NO_CLEANING)

        assert node.step == ElementClickStep(selector=selector, text=text, href=href)
        assert node.label == label
        assert node.step_is_exact is False

    def test_anchor_node_is_the_requested_element(self) -> None:
        node = node_from_key(
            NodeKey(kind="anchor", path="", tag="", element_id="", text="", href=""), ANCHOR, NO_CLEANING
        )

        assert node.is_anchor
        assert node.step == ANCHOR
        assert node.step_is_exact
        assert node.label == "Sign up"


class TestElementPathsQuerySerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_selector", {}, "selector"),
            ("bad_regex", {"selector": "a", "url": "(", "url_matching": "regex"}, "url"),
            ("no_steps", {"selector": "a", "steps_before": "0", "steps_after": "0"}, "non_field_errors"),
            ("too_many_steps", {"selector": "a", "steps_after": "5"}, "steps_after"),
        ]
    )
    def test_rejects_bad_params(self, _name: str, params: dict[str, str], error_key: str) -> None:
        serializer = ElementPathsQuerySerializer(data=params)

        assert not serializer.is_valid()
        assert error_key in serializer.errors


@patch(FLAG, return_value=True)
class TestElementPathsAPI(APIBaseTest):
    def _url(self, params: str = "selector=button.signup") -> str:
        return f"/api/projects/{self.team.id}/user_journeys/element_paths/?{params}"

    def test_flag_off_hides_the_api(self, flag: MagicMock) -> None:
        flag.return_value = False

        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_date_range_over_the_limit_is_rejected(self, _flag: MagicMock) -> None:
        response = self.client.get(self._url("selector=button&date_from=-60d"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "date_from"

    @parameterized.expand([("toolbar_scopes", None, status.HTTP_200_OK), ("no_query_scope", "action:read", 403)])
    def test_toolbar_oauth_token_needs_query_read(
        self, _flag: MagicMock, _name: str, scope: str | None, expected: int
    ) -> None:
        application = OAuthApplication.objects.create(
            name="Example toolbar",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_example_element_paths",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope or " ".join(settings.TOOLBAR_OAUTH_SCOPES),
        )
        self.client.logout()

        with patch(EXECUTE, return_value=HogQLQueryResponse(results=[(0, 0)])):
            response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token.token}")

        assert response.status_code == expected, response.content
        if expected == status.HTTP_200_OK:
            body = response.json()
            assert body["anchor_click_count"] == 0
            assert body["paths"] == []


@patch(FLAG, return_value=True)
class TestElementPathsClickhouse(ClickhouseTestMixin, APIBaseTest):
    def _click(self, team: Team, session: str, at: datetime, tag: str, classes: list[str], text: str, url: str) -> None:
        _create_event(
            team=team,
            event="$autocapture",
            distinct_id="visitor",
            timestamp=at,
            properties={"$session_id": session, "$current_url": url, "$event_type": "click"},
            elements=[Element(tag_name=tag, attr_class=classes, text=text, nth_child=0, nth_of_type=0)],
        )

    def _pageview(self, team: Team, session: str, at: datetime, url: str) -> None:
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="visitor",
            timestamp=at,
            properties={"$session_id": session, "$current_url": url},
        )

    def _session_through_signup(self, team: Team, session: str, start: datetime) -> None:
        self._pageview(team, session, start, "https://example.com/pricing")
        self._pageview(team, session, start + timedelta(seconds=5), "https://example.com/pricing?plan=pro")
        self._click(
            team,
            session,
            start + timedelta(seconds=10),
            "button",
            ["secondary"],
            "Learn more",
            "https://example.com/pricing",
        )
        self._click(
            team, session, start + timedelta(seconds=20), "button", ["signup"], "Sign up", "https://example.com/pricing"
        )
        self._pageview(team, session, start + timedelta(seconds=30), "https://example.com/signup")

    def _get(self, params: str = "") -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/user_journeys/element_paths/?selector=button.signup&text=Sign%20up&{params}"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_paths_through_the_clicked_element(self, _flag: MagicMock) -> None:
        start = timezone.now() - timedelta(hours=2)
        self._session_through_signup(self.team, "s1", start)
        self._session_through_signup(self.team, "s2", start + timedelta(minutes=10))
        # The same visitor has another tab open in a separate session at the same time.
        self._pageview(self.team, "s3", start + timedelta(seconds=15), "https://example.com/other")
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        for session in ("o1", "o2", "o3"):
            self._session_through_signup(other_team, session, start)
        flush_persons_and_events()

        body = self._get()

        assert (body["anchor_click_count"], body["anchor_session_count"], body["analyzed_session_count"]) == (2, 2, 2)
        [path] = body["paths"]
        assert [node["label"] for node in path["nodes"]] == ["/pricing", "Learn more", "Sign up", "/signup"]
        assert [node["is_anchor"] for node in path["nodes"]] == [False, False, True, False]
        assert (path["session_count"], path["share_of_anchor_sessions"], path["anchor_index"]) == (2, 1.0, 2)
        assert path["nodes"][2]["step"]["selector"] == "button.signup"

    @parameterized.expand([("no_clicks", False, (0, 0)), ("clicks_without_a_common_path", True, (2, 2))])
    def test_no_paths(self, _flag: MagicMock, _name: str, clicked: bool, counts: tuple[int, int]) -> None:
        start = timezone.now() - timedelta(hours=2)
        self._pageview(self.team, "s1", start, "https://example.com/pricing")
        self._pageview(self.team, "s2", start, "https://example.com/docs")
        if clicked:
            for session in ("s1", "s2"):
                self._click(
                    self.team,
                    session,
                    start + timedelta(seconds=5),
                    "button",
                    ["signup"],
                    "Sign up",
                    "https://example.com",
                )
        flush_persons_and_events()

        body = self._get()

        assert (body["anchor_click_count"], body["anchor_session_count"]) == counts
        assert body["paths"] == []
