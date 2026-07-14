from unittest.mock import MagicMock, patch

from products.pulse.backend.generation.expand import (
    ExpansionPlan,
    ExpansionProposal,
    execute_expansion,
    propose_expansions,
    valid_hogql,
)

LLM_PATH = "products.pulse.backend.generation.expand.MaxChatOpenAI"
EXECUTE_PATH = "products.pulse.backend.generation.expand.execute_hogql_query"


def _proposal(intent: str = "check signup drop") -> ExpansionProposal:
    return ExpansionProposal(intent=intent, hogql="SELECT count() FROM events")


def _mock_llm(plan: ExpansionPlan) -> MagicMock:
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = plan
    return llm


class TestProposeExpansions:
    async def test_propose_expansions_caps_to_max(self) -> None:
        plan = ExpansionPlan(proposals=[_proposal(f"intent {i}") for i in range(5)])
        with patch(LLM_PATH, return_value=_mock_llm(plan)):
            proposals = await propose_expansions(
                [{"title": "seed"}], team=MagicMock(), user=MagicMock(), focus_prompt="growth", max_proposals=3
            )
        assert len(proposals) == 3


class TestValidHogql:
    def test_valid_hogql_accepts_select(self) -> None:
        assert valid_hogql("SELECT count() FROM events") is True

    def test_valid_hogql_rejects_garbage(self) -> None:
        assert valid_hogql("not a query") is False

    def test_valid_hogql_rejects_non_select_statement(self) -> None:
        assert valid_hogql("DROP TABLE x") is False


class TestExecuteExpansion:
    def test_execute_expansion_rowcaps_into_source_item(self) -> None:
        proposal = _proposal("check signup drop")
        response = MagicMock(results=[(i,) for i in range(100)], columns=["count"])
        with patch(EXECUTE_PATH, return_value=response):
            item = execute_expansion(proposal, team=MagicMock(), max_rows=10)
        assert item is not None
        assert item.kind == "signal"
        assert item.source == "expansion"
        assert item.title == proposal.intent
        assert "10" in item.description

    def test_execute_expansion_returns_none_on_error(self) -> None:
        proposal = _proposal()
        with patch(EXECUTE_PATH, side_effect=ValueError("boom")):
            item = execute_expansion(proposal, team=MagicMock(), max_rows=10)
        assert item is None
