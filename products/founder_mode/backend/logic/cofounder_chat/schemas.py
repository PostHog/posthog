"""Schemas for the cofounder chat turn endpoint.

Chat is *ephemeral* on the backend right now — the request carries the full conversation
state, the response carries the agent's next move. We don't persist messages or canvas
notes until the founder commits to validation at the end of the chat phase. That choice
lets us avoid a `cards` migration and ship the LLM-driven chat over a single endpoint.

Frontend mirrors these shapes in `products/founder_mode/frontend/founderChatLogic.ts`.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Lean-canvas slots, matching the frontend's slot vocabulary in founderChatLogic.ts.
# Keep this list and the labels in sync.
CanvasSlotKey = Literal[
    "idea",
    "pain",
    "audience",
    "currentSolution",
    "worstCase",
    "success",
    "killerFeature",
]


class ChatMessageInput(BaseModel):
    """A prior message in the conversation. Used to give the agent context."""

    author: Literal["agent", "user"]
    value: str


class CanvasNoteInput(BaseModel):
    """A canvas slot that's already been filled. Used so the agent knows what's left to ask."""

    key: CanvasSlotKey
    label: str
    value: str


class TurnRequest(BaseModel):
    """What the frontend POSTs each turn."""

    user_answer: str = Field(description="The founder's latest reply.")
    last_question: str | None = Field(
        default=None, description="The agent's previous question this answer is responding to."
    )
    messages: list[ChatMessageInput] = Field(
        default_factory=list,
        description="Full conversation history so the agent can reference prior context.",
    )
    canvas_notes: list[CanvasNoteInput] = Field(
        default_factory=list,
        description="Slots already filled. The agent should not ask questions for these.",
    )


class CanvasSlotChoice(BaseModel):
    """The agent's decision about which canvas slot the latest answer should fill."""

    key: CanvasSlotKey
    label: str = Field(description="Display label for this slot, lifted from the frontend vocabulary.")
    value: str = Field(
        description=(
            "The crystallized value to write into this slot, extracted from the founder's answer. "
            "Should be a tightened version of what they said, not a verbatim quote."
        )
    )


class IdeationPayload(BaseModel):
    """Prose-form synthesis of the chat, ready to feed into the validation stage.

    This is NOT a copy of the canvas slot values. It's the agent's coherent retelling of
    the idea — written so the validation prompt has rich, narrative context instead of
    seven disconnected one-liners. Each field should be 1-3 sentences weaving in detail
    from the relevant slots."""

    what: str = Field(
        description=(
            "What the founder is building, in 1-3 sentences. Synthesizes from idea + "
            "killerFeature, with concrete texture about the mechanism."
        )
    )
    how: str = Field(
        description=(
            "How it works, in 1-2 sentences. The mechanism, channel, and delivery model — "
            "derived from idea + killerFeature."
        )
    )
    who: str = Field(
        description=(
            "Who it's for, in 1-2 sentences. Concrete demographic + behavioral signals — "
            "derived from audience. Use the founder's words where vivid."
        )
    )
    problem: str = Field(
        description=(
            "The problem this solves, in 2-4 sentences. Pull from pain + currentSolution + "
            "worstCase + success to capture not just the surface pain but the stakes and "
            "what success looks like. This is the richest field — validation reads it most carefully."
        )
    )


class TurnResponse(BaseModel):
    """What the backend returns each turn."""

    agent_message: str = Field(
        description=(
            "The cofounder's next message — usually a question, sometimes a declarative claim. "
            "≤30 words for the question proper; ≤2 short sentences if there's a preamble."
        ),
        max_length=400,
    )
    canvas_slot: CanvasSlotChoice | None = Field(
        default=None,
        description=(
            "If the user's preceding answer filled a slot, this is what to write. Null when the turn "
            "was conversational repair (clarifying question, banter) and didn't produce a slot value."
        ),
    )
    should_end_chat: bool = Field(
        default=False,
        description=(
            "True when at least the core slots (idea + pain + audience + one of "
            "currentSolution/worstCase/killerFeature) are filled AND the most recent answer was "
            "substantive enough to wrap. The frontend transitions to the review phase on true."
        ),
    )
    next_slot_hint: CanvasSlotKey | None = Field(
        default=None,
        description=(
            "Which slot the user's NEXT answer will most likely fill, given the question being "
            "asked in `agent_message`. UI hint only — used to label the input box. The actual slot "
            "extraction happens on the next turn via `canvas_slot`. Null when the agent is just "
            "doing conversational repair / banter and the next answer isn't tied to a slot."
        ),
    )
    ideation_payload: IdeationPayload | None = Field(
        default=None,
        description=(
            "REQUIRED when `should_end_chat` is true; null otherwise. A prose-form synthesis of "
            "everything learned in the chat, shaped for the validation stage's {what, how, who, "
            "problem} contract. This is what gets written to FounderProject.ideation. Do not "
            "copy slot values verbatim — synthesize coherently across slots."
        ),
    )
    reasoning: str = Field(
        description=(
            "Internal — what the agent noticed and what it most needs to know next, 1-2 sentences. "
            "Not shown to the founder, but logged for prompt tuning."
        )
    )
