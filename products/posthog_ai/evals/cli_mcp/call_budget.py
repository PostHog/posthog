from __future__ import annotations

import json

from products.posthog_ai.eval_harness.log_parser import EXEC_TOOL_NAME, LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


class MCPCallBudget(Scorer):
    def _name(self) -> str:
        return "mcp_call_budget"

    def _run_eval_sync(
        self,
        output: dict[str, object] | None,
        expected: dict[str, object] | None = None,
        **kwargs: object,
    ) -> Score:
        spec = (expected or {}).get(self._name(), {})
        if not isinstance(spec, dict):
            raise ValueError("mcp_call_budget must be an object")
        budget = spec.get("max_calls")
        if "max_calls" in spec and (type(budget) is not int or budget < 0):
            raise ValueError("mcp_call_budget.max_calls must be a nonnegative integer")

        raw_log = output.get("raw_log") if output else None
        if not isinstance(raw_log, str) or not raw_log.strip():
            return Score(
                name=self._name(),
                score=0.0 if budget is not None else None,
                metadata={"reason": "No raw log"},
            )

        prompt = output.get("prompt") if output else None
        parser = LogParser.cached(raw_log, initial_prompt=prompt if isinstance(prompt, str) else "")
        calls = [
            call
            for call in parser.get_tool_calls()
            if call.raw_name.startswith("mcp__posthog__") or call.raw_name == EXEC_TOOL_NAME
        ]
        signatures = {
            (
                call.name,
                json.dumps(
                    {key: value for key, value in call.input.items() if key not in {"context", "llm_model"}},
                    sort_keys=True,
                ),
            )
            for call in calls
        }
        return Score(
            name=self._name(),
            score=None if budget is None else float(len(calls) <= budget),
            metadata={
                "attempted_calls": len(calls),
                "failed_calls": sum(call.is_error for call in calls),
                "repeated_calls": len(calls) - len(signatures),
                "max_calls": budget,
            },
        )
