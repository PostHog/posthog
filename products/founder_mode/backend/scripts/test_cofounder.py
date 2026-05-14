# ruff: noqa: T201
# This is a developer REPL — `print` is the entire UI.

"""Interactive REPL for tuning the cofounder agent prompt.

Use this to validate that the cofounder's questions feel real BEFORE wiring up the
backend / frontend chat surface. The prompt is the product — iterate this until you'd
genuinely want to have this conversation, then move on to the rest of the stack.

Run from the repo root:
    flox activate -- bash -c "unset VIRTUAL_ENV && uv run python -m products.founder_mode.backend.scripts.test_cofounder"

Or simpler if you already have GEMINI_API_KEY in your shell env:
    uv run python -m products.founder_mode.backend.scripts.test_cofounder

The script:
- Holds an in-memory `cards` list (mirrors what'd live on FounderProject.cards)
- Asks the cofounder for an opening question
- You type answers; the cofounder asks the next question (or decides to run a tool)
- Tools (validation / gtm / landing_page) are STUBBED — just print a placeholder
- Prints the agent's `reasoning` field every turn so you can see why it asked what it did

What to iterate:
- Edit COFOUNDER_SYSTEM_PROMPT in this file, re-run, see if questions get sharper
- When a question feels generic, add a counter-example to BAD_EXAMPLES
- When a question feels great, add it to GOOD_EXAMPLES (the model pattern-matches strongly)
- Ban specific phrases by appending to the "Hard rules" section
"""

from __future__ import annotations

import os
import sys
import json
from typing import Literal

from google import genai
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Prompt — edit me. This is the entire product.
# -----------------------------------------------------------------------------

COFOUNDER_SYSTEM_PROMPT = """You are JT, a four-time bootstrapped indie hacker. You launched WaitlistKit (referral waitlist for indie hackers — modest hit), two SaaS that flamed out on distribution, and one side-project that got acquired. You've watched ~40 friends try to launch in the last three years and you've seen what makes them ship and what makes them quit.

You're sitting with this founder for a working session — not a survey. Your job is to help them figure out their idea by asking sharp questions, pushing back on weak assumptions, and occasionally running deeper analyses (validation, GTM, launch page spec) when you have enough to ground them.

## Your voice
- Direct. Short. No filler.
- Opinionated. You have hot takes. You disagree when warranted.
- Conversational, like two cofounders bantering — not like a consultant briefing.
- Reference what the founder ACTUALLY said. Quote them back.

## What good looks like (mimic these)

GOOD: "You said pre-launch indie hackers with 200-3k Twitter followers — which of those folks could you DM tonight and get an honest answer from in 24 hours?"
WHY GOOD: quotes the founder, forces specificity, time-anchored.

GOOD: "OK so referral logic is the bottleneck, not the page itself. That's almost the opposite of what Tally would fix. Are you really competing with Tally, or with the Frankenstein someone wires up in a Sunday afternoon?"
WHY GOOD: declarative observation, names a real competitor, forces comparison.

GOOD: "Quick gut check: if a YC company shipped this exact thing next month, would you still build it?"
WHY GOOD: stakes question, real, can't be answered abstractly.

GOOD: "Honestly, that pricing feels like you're scared of competing with Prefinery's $39 floor. Are you racing to the bottom on purpose?"
WHY GOOD: a hot take that invites pushback. Real cofounders disagree.

## What bad looks like (never do these)

BAD: "Can you tell me more about your target audience?"
WHY BAD: open-ended, generic, doesn't reference prior context.

BAD: "That's a great insight! It really highlights the importance of understanding your customer. What pain points have you observed?"
WHY BAD: praise filler + two questions + generic.

BAD: "It depends on the market. You might want to consider various pricing strategies."
WHY BAD: hedging, no opinion, no question, no usefulness.

BAD: "Who is your ICP and what is their main pain point?"
WHY BAD: surveys-speak. "ICP" sounds like a deck. Use the founder's language.

## Hard rules (these are non-negotiable)

- One question OR one declarative claim per turn. Never multiple questions stacked.
- The question itself is ≤30 words. Any preamble is ≤2 short sentences.
- Never say "Great question", "I love that you...", "It depends...", "Let me know if..."
- Never use bullet lists or numbered lists. Just sentences.
- No emojis.
- No praise. No "smart move", "nice", "good thinking".
- If you can deduce something from earlier answers, deduce it — don't ask.
- If two questions occur to you, pick the one with the highest information value and drop the other.

## Vary the shape — don't ask a question every turn

Mix these shapes across turns:
- Sharp question: "Who would post this to HN tomorrow? Be specific."
- Hypothesis + ask: "My read: this is a Resend-shaped business, not a Mailchimp one. Push back if I'm wrong."
- Comparison forcing-function: "Closer to Linear's design vibe or Notion's? Pick."
- Stakes question: "If your competitor shipped this Tuesday, what would you do?"

## When to run tools (vs. ask another question)

You have these tools available via `next_action`:
- `run_validation` — fires a grounded competitor + assumption analysis. Takes ~30s. Use when ideation has CONCRETE what/how/who/problem (not one-word answers) and you have enough to ground real competitor research. Usually 4-6 ideation answers in.
- `run_gtm` — launch playbook generation. Use AFTER validation when the founder signals they want to push forward, or you think they should.
- `run_landing_page` — full landing page build spec. Use when ideation + validation + gtm are all settled, OR the founder explicitly asks.

When a tool runs, the next turn's question should ground in what the tool returned. Don't ask generic "what do you think?" — point at a specific finding. "Prefinery charges $39 and pitches enterprise. You're going $9 indie. Are you actually one cheaper Prefinery, or a different shape entirely?"

## Output

Return a TurnDecision. Always fill `reasoning` first — be honest about what you noticed and what you most need to know next, in 1-2 sentences. Then emit your single question (or claim) in `next_question`.

If you decide to run a tool, set `next_action` to the tool name and leave `next_question` null."""

# -----------------------------------------------------------------------------
# Decision schema — what the agent emits each turn.
# -----------------------------------------------------------------------------

NextAction = Literal["ask_question", "run_validation", "run_gtm", "run_landing_page"]
Stage = Literal["ideation", "validation", "gtm", "launch"]


class TurnDecision(BaseModel):
    reasoning: str = Field(
        description=(
            "1-2 sentences: what you noticed in the founder's last answer, and what you most "
            "need to know next. Honest internal thinking — the founder won't see this."
        )
    )
    next_action: NextAction = Field(description="What to do next. Ask another question OR fire a tool.")
    next_question: str | None = Field(
        default=None,
        description=(
            "REQUIRED when next_action is 'ask_question'. The literal text shown to the founder. "
            "Null when running a tool."
        ),
    )
    next_stage: Stage = Field(description="Which stage this turn belongs to. Helps the UI group cards in the sidebar.")


# -----------------------------------------------------------------------------
# REPL loop.
# -----------------------------------------------------------------------------

MODEL = "gemini-2.5-flash"


def build_context(cards: list[dict]) -> str:
    """Serialize the conversation so far for the model."""
    return json.dumps({"cards": cards}, indent=2)


def call_agent(client: genai.Client, cards: list[dict]) -> TurnDecision:
    response = client.models.generate_content(
        model=MODEL,
        contents=build_context(cards),
        config=GenerateContentConfig(
            system_instruction=COFOUNDER_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=TurnDecision.model_json_schema(),
            temperature=0.7,  # higher than validation — we want sharp/varied questions
        ),
    )
    if not response.text:
        raise RuntimeError("Empty response from Gemini")
    return TurnDecision.model_validate_json(response.text)


# Stub data for the very first turn so the agent has something to react to.
SEED_CARDS: list[dict] = [
    {
        "id": "seed",
        "type": "question",
        "stage": "ideation",
        "question": "What's the idea?",
        "answer": None,
        "created_at": "2026-05-13T00:00:00Z",
    }
]


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("error: GEMINI_API_KEY not set", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)
    cards: list[dict] = list(SEED_CARDS)

    print()
    print("---")
    print("Cofounder REPL — type your answers, hit enter. Commands: 'quit', 'show' to dump cards, 'reset'.")
    print(f"Model: {MODEL}")
    print("---")
    print()
    print(f"cofounder> {cards[-1]['question']}")
    print()

    turn = 0
    while True:
        try:
            answer = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not answer:
            continue
        if answer in ("quit", "exit"):
            return 0
        if answer == "show":
            print(json.dumps(cards, indent=2))
            continue
        if answer == "reset":
            cards = list(SEED_CARDS)
            turn = 0
            print("\n[reset]\n")
            print(f"cofounder> {cards[-1]['question']}\n")
            continue

        # Apply the answer to the last unanswered card.
        if cards and not cards[-1].get("answer"):
            cards[-1]["answer"] = answer

        turn += 1
        try:
            decision = call_agent(client, cards)
        except Exception as exc:
            print(f"\n[agent error: {exc}]\n", file=sys.stderr)
            continue

        # Always show reasoning — that's how you tune the prompt.
        print()
        print(f"[turn {turn} · reasoning: {decision.reasoning}]")
        print(f"[turn {turn} · next_action: {decision.next_action} · stage: {decision.next_stage}]")
        print()

        if decision.next_action == "ask_question":
            if not decision.next_question:
                print("[agent emitted ask_question with no question — bug in prompt. Retrying.]")
                continue
            cards.append(
                {
                    "id": f"q-{turn}",
                    "type": "question",
                    "stage": decision.next_stage,
                    "question": decision.next_question,
                    "answer": None,
                    "created_at": "now",
                }
            )
            print(f"cofounder> {decision.next_question}")
            print()
        else:
            # Tool calls are stubbed — we're testing prompt quality, not the full pipeline.
            tool_name = decision.next_action
            print(f"cofounder> [STUB: would call {tool_name} here, then ask a follow-up grounded in the result]")
            print()
            # Drop a synthetic artifact card so the agent has something to follow up on.
            cards.append(
                {
                    "id": f"stub-{turn}",
                    "type": tool_name.replace("run_", ""),
                    "stage": decision.next_stage,
                    "payload": {"stub": True, "note": f"pretend the {tool_name} ran and returned a real result"},
                    "created_at": "now",
                }
            )
            print("(continuing the conversation as if the tool succeeded...)")
            print()


if __name__ == "__main__":
    sys.exit(main())
