"""Replay the researched-cause cases in fixtures/cases.json through the specificity gate prompt.

Runs the production system prompt and user-prompt builder against the production matching model,
with the same request shape that `call_llm` sends for that model. It calls Anthropic directly, so
it needs only ANTHROPIC_API_KEY and not the LLM gateway.

    DEBUG=1 PYTHONPATH=. python products/signals/eval/experiments/2026-10-researched-cause-gate/run_trial.py

Pass `--ref <git-ref>` to read the system prompt from another commit.
"""

import os
import re
import sys
import json
import asyncio
import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

import anthropic  # noqa: E402

from products.signals.backend.temporal.grouping import (  # noqa: E402
    SPECIFICITY_CHECK_SYSTEM_PROMPT,
    SpecificityResult,
    _build_specificity_prompt,
)
from products.signals.backend.temporal.llm import (  # noqa: E402
    MATCHING_MODEL,
    MAX_RESPONSE_TOKENS,
    _strip_markdown_json_fences,
    effort_kwargs,
)
from products.signals.backend.temporal.types import SignalData  # noqa: E402

HERE = Path(__file__).resolve().parent
GROUPING_PATH = "products/signals/backend/temporal/grouping.py"


def system_prompt_at(ref: str | None) -> str:
    if ref is None:
        return SPECIFICITY_CHECK_SYSTEM_PROMPT
    source = subprocess.check_output(["git", "show", f"{ref}:{GROUPING_PATH}"], text=True)
    match = re.search(r'SPECIFICITY_CHECK_SYSTEM_PROMPT = """(.*?)"""', source, re.S)
    if match is None:
        raise ValueError(f"no specificity prompt in {GROUPING_PATH} at {ref}")
    return match.group(1)


async def judge(client: anthropic.AsyncAnthropic, system: str, user: str) -> bool:
    response = await client.messages.create(
        model=MATCHING_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=MAX_RESPONSE_TOKENS,
        **effort_kwargs(MATCHING_MODEL),
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return SpecificityResult.model_validate_json(_strip_markdown_json_fences(text)).specific_enough


async def main(ref: str | None, repeats: int) -> None:
    data = json.loads((HERE / "fixtures" / "cases.json").read_text())
    group = data["group"]
    group_signals = [
        SignalData(
            signal_id=f"group-{i}",
            content=content,
            source_product="replay_vision",
            source_type="observation",
            source_id=f"group-{i}",
            weight=0.5,
            timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        )
        for i, content in enumerate(group["signals"])
    ]
    system = system_prompt_at(ref)
    client = anthropic.AsyncAnthropic()
    for case in data["cases"]:
        user = _build_specificity_prompt(
            new_signal_description=case["description"],
            new_signal_source_product="replay_vision",
            new_signal_source_type="observation",
            report_title=group["title"],
            group_signals=group_signals,
            researched_summary=group["researched_cause"],
        )
        verdicts = await asyncio.gather(*(judge(client, system, user) for _ in range(repeats)))
        correct = sum(verdict == case["expected_accept"] for verdict in verdicts)
        sys.stdout.write(
            f"{case['name']:36} expected_accept={case['expected_accept']!s:5} correct={correct}/{repeats}\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", default=None, help="Git ref to read the system prompt from")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.ref, args.repeats))
