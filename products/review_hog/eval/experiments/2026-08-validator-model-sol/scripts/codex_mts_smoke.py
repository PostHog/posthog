"""Throwaway smoke test: does MultiTurnSession follow-up work on the Codex adapter?

Three turns on one warm session pinned to codex / gpt-5.6-sol / xhigh / full-access:
  1. read a file, remember a random secret word            -> proves turn 1 + JSON validation
  2. recall the file + secret WITHOUT re-reading            -> proves the codex thread kept its history
  3. fetch the validation skill over MCP skill-get          -> proves MCP tools still work on a follow-up
Run:  DJANGO_SETTINGS_MODULE=posthog.settings python codex_mts_smoke.py
"""

import os
import sys
import json
import time
import asyncio
import logging
import secrets

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django  # noqa: E402

django.setup()

from pydantic import BaseModel  # noqa: E402

from products.review_hog.backend.reviewer.constants import REVIEW_MCP_SCOPES  # noqa: E402
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession  # noqa: E402
from products.tasks.backend.facade.api import TaskOriginProduct  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TEAM_ID = 1
USER_ID = 1
REPOSITORY = "PostHog/posthog"
FILE = "products/review_hog/backend/reviewer/constants.py"
SKILL = "review-hog-validation-criteria"
SECRET = f"hedgehog-{secrets.token_hex(3)}"


class Turn1(BaseModel):
    file_path: str
    line_count: int
    first_def_name: str
    secret_word: str


class Turn2(BaseModel):
    previous_file_path: str
    previous_secret_word: str
    previous_first_def_name: str
    used_tools_this_turn: bool


class Turn3(BaseModel):
    skill_found: bool
    skill_version: int | None = None
    first_heading: str | None = None
    previous_secret_word: str


def schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2)


PROMPT_1 = f"""You are running inside a sandbox with the {REPOSITORY} repository checked out.

Task:
1. Read the file `{FILE}`.
2. Count its lines (e.g. `wc -l`).
3. Find the name of the FIRST function defined with `def` in that file.
4. Remember this secret word for later turns: `{SECRET}`

Return ONLY a JSON object (no prose, no code fence) matching this schema:
{schema(Turn1)}
"""

PROMPT_2 = f"""Follow-up turn. Do NOT read any files and do NOT run any tools this turn.
Answer purely from our conversation so far:
- which file path did I ask you to read in the previous turn?
- what was the secret word I asked you to remember?
- what was the first `def` name you found?
Set `used_tools_this_turn` to true if you ran any tool anyway.

Return ONLY a JSON object (no prose, no code fence) matching this schema:
{schema(Turn2)}
"""

PROMPT_3 = f"""Follow-up turn. Use the PostHog MCP tool `skill-get` to fetch the skill named `{SKILL}` (latest version).
Report whether it was found, its version number, and the first markdown heading in its body.
Also repeat the secret word from turn 1.

Return ONLY a JSON object (no prose, no code fence) matching this schema:
{schema(Turn3)}
"""


def out(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


async def main() -> int:
    context = CustomPromptSandboxContext(
        team_id=TEAM_ID,
        user_id=USER_ID,
        repository=REPOSITORY,
        runtime_adapter="codex",
        model="gpt-5.6-sol",
        reasoning_effort="xhigh",
        initial_permission_mode="full-access",
        posthog_mcp_scopes=REVIEW_MCP_SCOPES,
    )
    print(f"secret={SECRET}", flush=True)
    t0 = time.monotonic()
    session, r1 = await MultiTurnSession.start(
        prompt=PROMPT_1,
        context=context,
        model=Turn1,
        step_name="codex-mts-smoke",
        output_fn=out,
        origin_product=TaskOriginProduct.REVIEW_HOG,
        internal=True,
        ai_stage="codex-mts-smoke",
    )
    print(f"task={session.task.id} run={session.task_run.id} log_url={session.task_run.log_url}", flush=True)
    print(f"TURN1 ({time.monotonic() - t0:.0f}s): {r1.model_dump_json()}", flush=True)
    ok = r1.secret_word == SECRET
    try:
        t1 = time.monotonic()
        r2 = await session.send_followup(PROMPT_2, Turn2, label="turn2-recall")
        print(f"TURN2 ({time.monotonic() - t1:.0f}s): {r2.model_dump_json()}", flush=True)
        ok &= r2.previous_secret_word == SECRET and r2.previous_file_path.endswith(FILE)
        t2 = time.monotonic()
        r3 = await session.send_followup(PROMPT_3, Turn3, label="turn3-mcp")
        print(f"TURN3 ({time.monotonic() - t2:.0f}s): {r3.model_dump_json()}", flush=True)
        ok &= r3.previous_secret_word == SECRET
    finally:
        await session.end()
    print(f"TOTAL {time.monotonic() - t0:.0f}s  RESULT={'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
