import json
from collections.abc import Iterator
from typing import Any

from parameterized import parameterized

from products.slack_app.backend.logic.reply_presentation import (
    ALL_COMPONENT_KINDS,
    BlockAssembler,
    ComponentChecker,
    ComponentKind,
    MetricComponent,
    ThrottledMessage,
    present_components,
)

INSIGHT_URL = "https://us.posthog.com/project/2/insights/abc12"
ANSWER = (
    "Weekly signups reached 1,204, down -12% on last week.\n\n"
    "| Country | Signups |\n| --- | --- |\n| US | 640 |\n| DE | 210 |\n\n"
    f"See {INSIGHT_URL}"
)
CARD = [{"type": "section", "text": {"type": "mrkdwn", "text": "Insight card"}}]


def _line(**component: Any) -> str:
    return json.dumps(component)


METRIC = _line(type="metric", label="Signups", value="1,204")
LINK = _line(type="link", label="Open insight", url=INSIGHT_URL)
TABLE = _line(type="table", columns=["Country", "Signups"], rows=[["US", "640"], ["DE", "210"]])
RESOURCE = _line(type="resource", url=INSIGHT_URL)


def _render_resource(url: str) -> list[dict[str, Any]] | None:
    return CARD if url == INSIGHT_URL else None


def _types(blocks: list[dict[str, Any]]) -> list[str]:
    return [block["type"] for block in blocks]


class TestComponentChecker:
    @parameterized.expand(
        [
            ("metric", METRIC, ALL_COMPONENT_KINDS, True),
            ("link", LINK, ALL_COMPONENT_KINDS, True),
            ("table", TABLE, ALL_COMPONENT_KINDS, True),
            ("resource", RESOURCE, ALL_COMPONENT_KINDS, True),
            ("chart", _line(type="chart", url=INSIGHT_URL, title="Signups"), ALL_COMPONENT_KINDS, True),
            ("invented_value", _line(type="metric", label="Signups", value="1,300"), ALL_COMPONENT_KINDS, False),
            ("rounded_value", _line(type="metric", label="Signups", value="1.2k"), ALL_COMPONENT_KINDS, False),
            ("invented_cell", _line(type="table", columns=["Country"], rows=[["FR"]]), ALL_COMPONENT_KINDS, False),
            ("ragged_row", _line(type="table", columns=["A", "B"], rows=[["US"]]), ALL_COMPONENT_KINDS, False),
            (
                "url_not_in_answer",
                _line(type="link", label="Open", url="https://example.com"),
                ALL_COMPONENT_KINDS,
                False,
            ),
            ("not_https", _line(type="resource", url="javascript:alert(1)"), ALL_COMPONENT_KINDS, False),
            ("unknown_type", _line(type="carousel"), ALL_COMPONENT_KINDS, False),
            ("not_json", "Here are the components:", ALL_COMPONENT_KINDS, False),
            ("kind_not_offered", RESOURCE, frozenset({"metric", "link"}), False),
        ]
    )
    def test_only_grounded_components_inside_the_offered_catalog_pass(
        self, _name: str, line: str, kinds: frozenset[ComponentKind], passes: bool
    ) -> None:
        checker = ComponentChecker(ANSWER, kinds)

        assert (checker.check(line) is not None) == passes
        assert bool(checker.rejections) != passes

    def test_a_kind_past_its_limit_is_dropped(self) -> None:
        checker = ComponentChecker(ANSWER, ALL_COMPONENT_KINDS)

        results = [checker.check(LINK) for _ in range(4)]

        assert [result is not None for result in results] == [True, True, True, False]


class TestBlockAssembler:
    def test_a_stream_gets_each_group_once_it_is_settled_and_the_links_last(self) -> None:
        assembler = BlockAssembler(_render_resource)
        checker = ComponentChecker(ANSWER, ALL_COMPONENT_KINDS)
        appended: list[list[str]] = []
        for line in [METRIC, LINK, _line(type="metric", label="Change", value="-12%"), TABLE, METRIC]:
            component = checker.check(line)
            assert component is not None
            assembler.add(component)
            appended.append(_types(assembler.take_settled(final=False)))
        appended.append(_types(assembler.take_settled(final=True)))

        # Two metrics in a row share one section, which settles only when the table follows it.
        assert appended == [[], [], [], ["section", "table"], [], ["section", "actions"]]
        assert len(assembler.snapshot()[0]["fields"]) == 2

    def test_metric_text_cannot_inject_slack_mentions(self) -> None:
        assembler = BlockAssembler(_render_resource)
        assembler.add(MetricComponent(type="metric", label="<!channel> Signups", value="1,204"))

        text = assembler.snapshot()[0]["fields"][0]["text"]

        assert "<!channel>" not in text
        assert "&lt;!channel&gt;" in text


class TestPresentComponents:
    @parameterized.expand(
        [
            ("clean", None, ["section", "actions"]),
            ("call_fails_midway", RuntimeError, ["section"]),
        ]
    )
    def test_components_show_as_their_lines_complete_and_bad_lines_drop(
        self, _name: str, failure: type[Exception] | None, final_blocks: list[str]
    ) -> None:
        def deltas() -> Iterator[str]:
            # Lines split across chunks, as a streamed reply sends them.
            yield METRIC[:10]
            yield METRIC[10:] + "\nnot a component\n"
            if failure is not None:
                raise failure("gateway dropped the stream")
            yield LINK

        delivered: list[tuple[bool, list[str]]] = []
        outcome = present_components(
            deltas(),
            ComponentChecker(ANSWER, ALL_COMPONENT_KINDS),
            BlockAssembler(_render_resource),
            lambda assembler, final: delivered.append((final, _types(assembler.snapshot()))),
        )

        assert delivered[0] == (False, ["section"])
        assert delivered[-1] == (True, final_blocks)
        assert len(outcome.rejections) == 1
        assert outcome.error == (failure.__name__ if failure else None)


class TestThrottledMessage:
    def test_edits_wait_for_the_interval_but_the_last_one_always_goes_out(self) -> None:
        now = [0.0]
        posts: list[list[dict[str, Any]]] = []
        updates: list[list[dict[str, Any]]] = []
        message = ThrottledMessage(
            post=lambda blocks: posts.append(blocks) or "1.0",
            update=lambda _ts, blocks: updates.append(blocks) is None,
            clock=lambda: now[0],
            interval=0.5,
        )

        message.show([{"n": 1}])
        now[0] = 0.2
        message.show([{"n": 2}])
        now[0] = 0.3
        message.show([{"n": 3}], final=True)

        assert posts == [[{"n": 1}]]
        assert updates == [[{"n": 3}]]
        assert message.ts == "1.0"
