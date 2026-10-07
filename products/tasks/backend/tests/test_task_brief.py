import json

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.oauth import MCP_READ_SCOPES

from products.tasks.backend.logic.services.mcp_tool_names import MAX_MCP_TOOL_NAMES, MCP_ALLOWED_TOOLS_STATE_KEY
from products.tasks.backend.logic.services.task_brief import (
    BriefCandidates,
    BriefError,
    ModelCandidate,
    SkillCandidate,
    TaskBrief,
    ToolCandidate,
    parse_brief,
    render_run_message,
    scopes_for_tools,
    write_brief,
)
from products.tasks.backend.models import Task, TaskRun

SONNET = ModelCandidate(
    model="claude-sonnet-5-5", runtime_adapter="claude", label="Sonnet", supported_efforts=("low", "high")
)
CODEX = ModelCandidate(model="gpt-6.1-sol", runtime_adapter="codex", label="Sol", supported_efforts=("medium",))

CANDIDATES = BriefCandidates(
    models=(SONNET, CODEX),
    skills=(SkillCandidate(name="error-triage", version=2, description="Triage an error spike."),),
    tools=(
        ToolCandidate(
            name="insights-list", summary="List insights.", read_only=True, required_scopes=("insight:read",)
        ),
        ToolCandidate(
            name="insights-create", summary="Create an insight.", read_only=False, required_scopes=("insight:write",)
        ),
        ToolCandidate(name="query-run", summary="Run a query.", read_only=True, required_scopes=("query:read",)),
    ),
    default_model="claude-sonnet-5-5",
    default_reasoning_effort="high",
)

REQUEST = "Find out why signups dropped last week\nand write it up."


def _answer(**overrides: object) -> str:
    payload: dict[str, object] = {
        "title": "Investigate the signup drop",
        "prompt": "Look at signups over the last two weeks and explain the drop.",
        "model": "claude-sonnet-5-5",
        "reasoning_effort": "low",
        "skills": ["error-triage"],
        "tools": ["insights-list", "query-run"],
        "rationale": "Reads only.",
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestParseBrief(SimpleTestCase):
    def test_a_well_formed_answer_keeps_every_choice(self) -> None:
        brief = parse_brief(_answer(), REQUEST, CANDIDATES)

        self.assertEqual(brief.title, "Investigate the signup drop")
        self.assertEqual(brief.model, "claude-sonnet-5-5")
        self.assertEqual(brief.runtime_adapter, "claude")
        self.assertEqual(brief.reasoning_effort, "low")
        self.assertEqual(brief.skill_names, ("error-triage",))
        self.assertEqual(brief.allowed_mcp_tools, ("insights-list", "query-run"))

    @parameterized.expand(
        [
            ("unknown_model_falls_back_to_default", {"model": "claude-opus-1"}, "claude-sonnet-5-5", "claude"),
            ("null_model_falls_back_to_default", {"model": None}, "claude-sonnet-5-5", "claude"),
            ("other_runtime_follows_its_model", {"model": "gpt-6.1-sol"}, "gpt-6.1-sol", "codex"),
        ]
    )
    def test_model_is_clamped_to_the_catalogue(self, _name: str, overrides: dict, model: str, runtime: str) -> None:
        brief = parse_brief(_answer(**overrides), REQUEST, CANDIDATES)

        self.assertEqual((brief.model, brief.runtime_adapter), (model, runtime))

    @parameterized.expand(
        [
            ("unsupported_effort_uses_default", {"reasoning_effort": "max"}, "high"),
            ("default_not_supported_by_model_yields_none", {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}, None),
        ]
    )
    def test_effort_is_clamped_to_what_the_model_supports(
        self, _name: str, overrides: dict, effort: str | None
    ) -> None:
        self.assertEqual(parse_brief(_answer(**overrides), REQUEST, CANDIDATES).reasoning_effort, effort)

    def test_unknown_skills_and_tools_are_dropped(self) -> None:
        tools = ["INSIGHTS-LIST", "nope", "query-run", "insights-list"]
        brief = parse_brief(_answer(skills=["error-triage", "missing"], tools=tools), REQUEST, CANDIDATES)

        self.assertEqual(brief.skill_names, ("error-triage",))
        self.assertEqual(brief.allowed_mcp_tools, ("insights-list", "query-run"))

    def test_tools_are_capped_after_unknown_names_are_dropped(self) -> None:
        many = tuple(
            ToolCandidate(name=f"tool-{i}", summary="A tool.", read_only=True, required_scopes=("insight:read",))
            for i in range(MAX_MCP_TOOL_NAMES + 5)
        )
        candidates = BriefCandidates(
            models=(SONNET,), skills=(), tools=many, default_model=None, default_reasoning_effort=None
        )
        requested = ["nope"] * 10 + [tool.name for tool in many]

        brief = parse_brief(_answer(tools=requested), REQUEST, candidates)

        self.assertEqual(len(brief.allowed_mcp_tools), MAX_MCP_TOOL_NAMES)
        self.assertEqual(brief.allowed_mcp_tools[0], "tool-0")

    def test_missing_title_falls_back_to_the_request_first_line(self) -> None:
        self.assertEqual(
            parse_brief(_answer(title="  "), REQUEST, CANDIDATES).title, "Find out why signups dropped last week"
        )

    @parameterized.expand(
        [
            ("fenced", "```json\n{answer}\n```"),
            ("prose_around", "Here you go:\n{answer}\nDone."),
        ]
    )
    def test_json_is_found_inside_other_text(self, _name: str, template: str) -> None:
        text = template.format(answer=_answer())

        self.assertEqual(parse_brief(text, REQUEST, CANDIDATES).model, "claude-sonnet-5-5")

    @parameterized.expand([("not_json", "sure thing"), ("no_prompt", json.dumps({"title": "x", "prompt": ""}))])
    def test_an_unusable_answer_raises(self, _name: str, text: str) -> None:
        with self.assertRaises(BriefError):
            parse_brief(text, REQUEST, CANDIDATES)


class TestScopesForTools(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_tools_is_read_only", (), []),
            ("read_tools_add_no_writes", ("insights-list", "query-run"), []),
            ("write_tool_adds_its_scope", ("insights-list", "insights-create"), ["insight:write"]),
        ]
    )
    def test_reads_plus_declared_writes(self, _name: str, tools: tuple[str, ...], writes: list[str]) -> None:
        self.assertEqual(scopes_for_tools(tools, CANDIDATES), [*MCP_READ_SCOPES, *writes])


class TestRenderRunMessage(SimpleTestCase):
    def test_prompt_and_original_request_are_both_present(self) -> None:
        brief = parse_brief(_answer(), REQUEST, CANDIDATES)

        message = render_run_message(brief, REQUEST, [])

        self.assertIn("<user_custom_instructions>", message)
        self.assertIn(brief.prompt, message)
        self.assertIn("<original_request>", message)
        self.assertIn("Find out why signups dropped last week", message)


class TestWriteBrief(BaseTest):
    def test_brief_lands_on_the_task_and_its_run(self) -> None:
        task = Task.objects.create(
            team=self.team,
            title="placeholder",
            description=REQUEST,
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        task_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            state={"pending_dispatch": {"posthog_mcp_scopes": "read_only", "user_id": self.user.id}},
        )
        brief = TaskBrief(
            title="Investigate the signup drop",
            prompt="Explain the drop.",
            model="gpt-6.1-sol",
            runtime_adapter="codex",
            reasoning_effort="medium",
            skill_names=("error-triage",),
            allowed_mcp_tools=("insights-list", "insights-create"),
            rationale="Needs a write.",
        )

        scopes = write_brief(task, task_run, brief, candidates=CANDIDATES)

        task.refresh_from_db()
        task_run.refresh_from_db()
        self.assertEqual(task.title, "Investigate the signup drop")
        self.assertEqual(task.description, REQUEST)
        self.assertEqual(task_run.state["pending_dispatch"]["posthog_mcp_scopes"], scopes)
        self.assertEqual(task_run.state["pending_dispatch"]["user_id"], self.user.id)
        self.assertEqual(task_run.state[MCP_ALLOWED_TOOLS_STATE_KEY], ["insights-list", "insights-create"])
        self.assertEqual(task_run.state["model"], "gpt-6.1-sol")
        self.assertEqual(task_run.state["runtime_adapter"], "codex")
        self.assertEqual(task_run.state["reasoning_effort"], "medium")
        self.assertIn("Explain the drop.", task_run.state["initial_prompt_override"])
        self.assertIn("`error-triage` (v2)", task_run.state["initial_prompt_override"])
