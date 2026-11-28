from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value

from products.access_control.backend.facade.testing import create_access_control
from products.today.backend.facade.contracts import (
    WorkContext,
    WorkFact,
    WorkHelper,
    WorkItem,
    WorkLine,
    WorkOption,
    WorkRun,
    WorkSource,
    WorkStartedFrom,
    WorkStep,
    WorkThread,
    WorkThreadInvalid,
)
from products.today.backend.facade.enums import WorkHelperMode, WorkOptionKind, WorkRunType
from products.today.backend.facade.testing import assert_work_threads_well_formed
from products.today.backend.logic import work_registry, work_threads
from products.today.backend.presentation.serializers import WorkThreadsSerializer
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin


def option(key: str, kind: WorkOptionKind = WorkOptionKind.NEXT) -> WorkOption:
    return WorkOption(
        key=key,
        kind=kind,
        label="Roll out to everyone",
        why="The release has run for 7 days without errors.",
        helper=WorkHelper(
            mode=WorkHelperMode.IN_PLACE,
            product="Feature flags",
            does="Sets the flag's rollout to 100%.",
            fields=[WorkFact(label="Rollout", value="100%")],
            run_label="Roll out",
            run=WorkRun(type=WorkRunType.ACTION, action_id="flag_rollout", params={"rollout": 100}),
            mcp_tools=["feature-flags-update"],
        ),
    )


def step(key: str, options: list[WorkOption] | None = None, alongside: list[WorkLine] | None = None) -> WorkStep:
    return WorkStep(
        key=key,
        title="Release to beta users",
        description="The new checkout runs for beta users.",
        area="Release",
        item=None,
        facts=[],
        options=options or [],
        alongside=alongside or [],
    )


def thread(key: str = "release:1", line: WorkLine | None = None) -> WorkThread:
    return WorkThread(
        key=key,
        name="Ship the new checkout",
        line=line
        or WorkLine(
            key="main",
            steps=[
                step("created"),
                step("beta", [option("roll_out"), option("experiment", WorkOptionKind.ALONGSIDE)]),
            ],
        ),
    )


def with_alongside(steps: list[WorkStep]) -> WorkThread:
    return thread(
        key="release:2",
        line=WorkLine(key="main", steps=[step("created"), step("beta", alongside=[WorkLine(key="side", steps=steps)])]),
    )


def declaring(*sources: object) -> SimpleNamespace:
    return SimpleNamespace(__name__="products.example.backend.facade.today_work", WORK_SOURCES=sources)


def no_threads(_context: WorkContext) -> list[WorkThread]:
    return []


class TestWorkRegistry(SimpleTestCase):
    @parameterized.expand(
        [
            ("no declaration", SimpleNamespace(__name__="products.example.backend.facade.today_work")),
            (
                "a single source without a tuple",
                SimpleNamespace(
                    __name__="products.example.backend.facade.today_work",
                    WORK_SOURCES=WorkSource(name="releases", find=no_threads),
                ),
            ),
            ("not a source", declaring("releases")),
            ("an empty name", declaring(WorkSource(name="", find=no_threads))),
            ("a find that cannot be called", declaring(WorkSource(name="releases", find=cast(Any, "find")))),
            (
                "scopes as one string",
                declaring(WorkSource(name="releases", find=no_threads, scopes=cast(Any, "release:read"))),
            ),
            (
                "a scope that is not object:action",
                declaring(WorkSource(name="releases", find=no_threads, scopes=("release",))),
            ),
            (
                "a name taken twice",
                declaring(WorkSource(name="releases", find=no_threads), WorkSource(name="releases", find=no_threads)),
            ),
        ]
    )
    def test_a_broken_declaration_raises(self, _name: str, module: SimpleNamespace) -> None:
        with patch.object(work_registry, "load_product_modules", return_value=[module]):
            with self.assertRaises(work_registry.WorkRegistryError):
                work_registry.load_registry.__wrapped__()

    def test_each_source_belongs_to_the_product_that_declares_it(self) -> None:
        release = SimpleNamespace(
            __name__="products.release.backend.facade.today_work",
            WORK_SOURCES=(WorkSource(name="releases", find=no_threads, scopes=("feature_flag:read",)),),
        )
        experiments = SimpleNamespace(
            __name__="products.experiments.backend.facade.today_work",
            WORK_SOURCES=(WorkSource(name="experiments", find=no_threads),),
        )

        with patch.object(work_registry, "load_product_modules", return_value=[release, experiments]):
            registry = work_registry.load_registry.__wrapped__()

        self.assertEqual(dict(registry.products), {"releases": "release", "experiments": "experiments"})
        self.assertEqual(list(registry.sources), ["experiments", "releases"])


class TestWorkThreadShape(SimpleTestCase):
    def test_a_well_formed_thread_with_an_alongside_line_passes(self) -> None:
        assert_work_threads_well_formed([thread(), with_alongside([step("experiment", [option("ship")])])])

    @parameterized.expand(
        [
            ("not a list", (thread(),), "must return a list"),
            ("a thread key twice", [thread(), thread()], "thread key 'release:1' twice"),
            (
                "a step key twice in one line",
                [thread(line=WorkLine(key="main", steps=[step("a"), step("a")]))],
                "step key 'a'",
            ),
            (
                "a step key of the main line again in an alongside line",
                [with_alongside([step("beta")])],
                "step key 'beta'",
            ),
            (
                "a line key twice",
                [
                    thread(
                        line=WorkLine(
                            key="main", steps=[step("a", alongside=[WorkLine(key="main", steps=[step("b")])])]
                        )
                    )
                ],
                "line key 'main'",
            ),
            (
                "an option key twice in a step",
                [thread(line=WorkLine(key="main", steps=[step("a", [option("go"), option("go")])]))],
                "option key twice in step 'a'",
            ),
            (
                "options on a step the line moved past",
                [thread(line=WorkLine(key="main", steps=[step("a", [option("go")]), step("b")]))],
                "not the last of line 'main'",
            ),
            ("a line without steps", [with_alongside([])], "line 'side' of thread 'release:2' without steps"),
        ]
    )
    def test_a_malformed_result_names_the_source_and_the_problem(self, _name: str, threads: Any, problem: str) -> None:
        with self.assertRaises(WorkThreadInvalid) as raised:
            work_threads.validate_threads("releases", threads)

        self.assertIn("'releases'", str(raised.exception))
        self.assertIn(problem, str(raised.exception))

    @parameterized.expand(
        [
            ("a link without a path", {"type": WorkRunType.LINK}),
            ("a link with an action id", {"type": WorkRunType.LINK, "to": "/flags/1", "action_id": "flag_rollout"}),
            ("an action without an id", {"type": WorkRunType.ACTION}),
            ("an action with a path", {"type": WorkRunType.ACTION, "action_id": "flag_rollout", "to": "/flags/1"}),
        ]
    )
    def test_a_run_that_cannot_run_fails_to_build(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            WorkRun(**kwargs)

    def test_the_payload_has_the_frontend_field_names_at_every_depth(self) -> None:
        step_with_everything = replace(
            step("experiment", [option("ship")]),
            item=WorkItem(
                type="experiment",
                id="7",
                name="Checkout test",
                kind_label="experiment",
                product="Experiments",
                href="/experiments/7",
            ),
            started_from=WorkStartedFrom(label="Run an experiment", why="Beta users convert less."),
        )

        payload = WorkThreadsSerializer({"results": [with_alongside([step_with_everything])]}).data

        main_step = payload["results"][0]["line"]["steps"][1]
        side_step = main_step["alongside"][0]["steps"][0]
        assert set(payload["results"][0]) == {"key", "name", "line"}
        assert set(main_step) == {
            "key",
            "title",
            "description",
            "area",
            "item",
            "facts",
            "chosen_label",
            "started_from",
            "options",
            "alongside",
        }
        assert (main_step["item"], main_step["chosen_label"], main_step["started_from"]) == (None, None, None)
        assert side_step["item"] == {
            "type": "experiment",
            "id": "7",
            "name": "Checkout test",
            "kind_label": "experiment",
            "product": "Experiments",
            "href": "/experiments/7",
        }
        assert side_step["started_from"] == {"label": "Run an experiment", "why": "Beta users convert less."}
        assert side_step["options"][0] == {
            "key": "ship",
            "kind": "next",
            "label": "Roll out to everyone",
            "why": "The release has run for 7 days without errors.",
            "gate": None,
            "helper": {
                "mode": "in_place",
                "product": "Feature flags",
                "does": "Sets the flag's rollout to 100%.",
                "fields": [{"label": "Rollout", "value": "100%"}],
                "run_label": "Roll out",
                "run": {"type": "action", "to": None, "action_id": "flag_rollout", "params": {"rollout": 100}},
                "mcp_tools": ["feature-flags-update"],
            },
        }


class TestWorkThreadsAPI(TodayTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.seen: list[WorkContext] = []

    def _find(self, context: WorkContext) -> list[WorkThread]:
        self.seen.append(context)
        return [thread(key=f"release:{context.ref}")]

    def _get(
        self,
        query: dict[str, str],
        flag: bool = True,
        team_id: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        source = WorkSource(name="releases", find=self._find, scopes=("feature_flag:read",))
        registry = work_registry.WorkRegistry(sources={"releases": source}, products={"releases": "release"})
        with (
            patch("products.today.backend.feature_flags.feature_enabled_or_false", return_value=flag),
            patch.object(work_threads, "load_registry", return_value=registry),
        ):
            return self.client.get(
                f"/api/projects/{team_id or self.team.id}/today/work_threads/", query, headers=headers
            )

    def test_the_source_builds_the_thread_of_the_ref_for_this_team_and_viewer(self) -> None:
        response = self._get({"source": "releases", "ref": "42"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [found["key"] for found in response.json()["results"]] == ["release:42"]
        assert [(context.team.id, context.user.id, context.ref) for context in self.seen] == [
            (self.team.id, self.user.id, "42")
        ]

    @parameterized.expand(
        [
            ("an unknown source", {"source": "nope"}, status.HTTP_400_BAD_REQUEST, "source"),
            ("no source", {}, status.HTTP_400_BAD_REQUEST, "source"),
            ("the flag off", {"source": "releases"}, status.HTTP_404_NOT_FOUND, None),
        ]
    )
    def test_the_source_is_not_called_for(
        self, _name: str, query: dict[str, str], expected: int, attr: str | None
    ) -> None:
        response = self._get(query, flag=expected != status.HTTP_404_NOT_FOUND)

        assert response.status_code == expected
        if attr is not None:
            assert response.json()["attr"] == attr
        assert self.seen == []

    @parameterized.expand(
        [
            ("a key with only today", ["today:read"], None, status.HTTP_403_FORBIDDEN),
            ("a key with today and the source's scope", ["today:read", "feature_flag:read"], None, status.HTTP_200_OK),
            ("a member without access to the source's resource", None, "none", status.HTTP_403_FORBIDDEN),
            ("a member with viewer access", None, "viewer", status.HTTP_200_OK),
        ]
    )
    def test_the_viewer_needs_the_scopes_the_source_declares(
        self, _name: str, key_scopes: list[str] | None, access_level: str | None, expected: int
    ) -> None:
        headers: dict[str, str] = {}
        if key_scopes is not None:
            raw_key = "today_work_threads_key"
            PersonalAPIKey.objects.create(
                user=self.user, label="Today", secure_value=hash_key_value(raw_key), scopes=key_scopes
            )
            self.client.logout()
            headers["Authorization"] = f"Bearer {raw_key}"
        if access_level is not None:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            create_access_control(team_id=self.team.id, resource="feature_flag", access_level=access_level)
            self.client.force_login(User.objects.create_and_join(self.organization, "member@example.com", "testtest"))

        response = self._get({"source": "releases", "ref": "42"}, headers=headers)

        assert response.status_code == expected
        held = None if key_scopes is None else frozenset(key_scopes)
        assert [context.scopes for context in self.seen] == ([held] if expected == status.HTTP_200_OK else [])
        if key_scopes is not None and expected == status.HTTP_403_FORBIDDEN:
            assert "feature_flag:read" in response.json()["detail"]

    def test_another_organizations_project_is_not_read(self) -> None:
        other = Team.objects.create(organization=Organization.objects.create(name="Other"))

        response = self._get({"source": "releases", "ref": "42"}, team_id=other.id)

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        assert self.seen == []
