"""Schemas for the cofounder chat turn endpoint.

Topic-scoped mini-chat: each call is one turn of a focused back-and-forth about a SINGLE
topic (currently just "idea" — the ideation step). The cofounder probes with follow-ups
until it genuinely has enough, then sets `satisfied` and returns a `crystallized_value`.

Chat is *ephemeral* on the backend — the request carries the topic's whole thread, the
response carries the next turn. Only the crystallized value persists (the frontend writes
it to FounderProject.ideation). No migration, single endpoint.

API note: the `cofounder_turn` viewset action and `run_chat_turn` signature are unchanged —
only the internal shapes of TurnRequest/TurnResponse moved from lean-canvas-slot filling to
topic-scoped probing. Frontend mirrors these shapes in
`products/founder_mode/frontend/cofounderFlowLogic.ts`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Which half of the founding team the cofounder plays. A solo founder is usually missing
# one — the cofounder complements them. Assigned 50/50 on the frontend (no picker for v1).
FounderMode = Literal["technical_cofounder", "commercial_cofounder"]

# Reaction key the cofounder picks per turn — drives a GIF reaction in the UI. Keep this
# short and tied to the cofounder's posture, not the founder's answer. The frontend maps
# the key to a GIF URL; the LLM picks the key under constrained decoding so it can never
# return an unknown value.
ReactionKey = Literal[
    "excited",
    "skeptical",
    "thinking",
    "satisfied",
    "dismissive",
]


class ChatMessageInput(BaseModel):
    """A prior message in this topic's mini-chat thread."""

    author: Literal["agent", "user"]
    value: str


class TurnRequest(BaseModel):
    """What the frontend POSTs each turn of a topic's mini-chat."""

    topic: str = Field(
        description='Which topic this mini-chat is about. Currently always "idea" (the ideation step).',
    )
    goal: str = Field(
        description=(
            "What the cofounder must extract from this topic before it can be satisfied. "
            "Topic-specific — the frontend defines it. For the idea topic this describes the "
            "{what, how, who, problem} the validation pass needs, and tells the cofounder which "
            "keys `crystallized_value` must carry."
        ),
    )
    user_answer: str = Field(description="The founder's latest reply in this thread.")
    messages: list[ChatMessageInput] = Field(
        default_factory=list,
        description="This topic's prior thread (everything before `user_answer`). Empty on the first turn.",
    )
    founder_mode: FounderMode = Field(
        default="commercial_cofounder",
        description=(
            "Which half of the founding team the cofounder plays. Selects the mode block "
            "injected into the system prompt. Defaults to commercial so older clients still "
            "get a coherent persona."
        ),
    )


class TurnResponse(BaseModel):
    """What the backend returns each turn."""

    agent_message: str = Field(
        description=(
            "The cofounder's next message — a sharp follow-up question or a declarative claim. "
            "≤30 words for the question proper; ≤2 short sentences if there's a preamble. When "
            "`satisfied` is true this is a brief 'got it, moving on' beat."
        ),
        max_length=400,
    )
    satisfied: bool = Field(
        default=False,
        description=(
            "True when the cofounder has genuinely extracted enough on this topic to move on. "
            "False means the thread continues and `agent_message` is a follow-up. Do not set this "
            "true on a thin or one-word answer just to advance."
        ),
    )
    crystallized_value: dict[str, Any] | None = Field(
        default=None,
        description=(
            "REQUIRED when `satisfied` is true; null otherwise. The distilled output of this "
            "topic's conversation. Shape is topic-defined by the request `goal`: for the idea "
            "topic the keys are `what`, `how`, `who`, `problem` — each a synthesized prose "
            "string (a tightened coherent retelling, not a verbatim quote). The frontend writes "
            "this straight into FounderProject.ideation."
        ),
    )
    reasoning: str = Field(
        description=(
            "Internal — what the cofounder noticed and what it still needs (or why it's now "
            "satisfied), 1-2 sentences. Not shown to the founder; logged for prompt tuning."
        )
    )
    reaction_key: ReactionKey = Field(
        description=(
            "The cofounder's posture on this turn, used to drive a GIF reaction in the UI. "
            "Pick the single key that best matches the *tone* of `agent_message`. "
            "See the system prompt's 'Reactions' section for when to pick each."
        )
    )
