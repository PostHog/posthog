from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Optional, Protocol
from uuid import UUID

from posthog.schema import MaxBillingContext

if TYPE_CHECKING:
    from posthog.models import Team, User


@dataclass(frozen=True)
class SlashCommandContext:
    """Everything a command core may need, resolvable by both the LangGraph and sandbox runtimes."""

    team: "Team"
    user: "User"
    conversation_id: UUID
    trace_id: str | None = None
    # LangGraph passes it from the RunnableConfig configurable; the sandbox passes None —
    # get_ai_usage_period(team, billing_context=None) already falls back to the org billing
    # period → past 30 days.
    billing_context: MaxBillingContext | dict[str, object] | None = None
    # Sandbox generations never carry $ai_session_id (the llm-gateway posthog callback only sets
    # $ai_trace_id/team_id/distinct_id), so the per-conversation credits query returns 0 there.
    # LangGraph attribution works and must not regress — the usage core branches on this flag:
    # True → include the per-conversation line, False → omit it.
    conversation_attribution_available: bool = True


@dataclass(frozen=True)
class TranscriptMessage:
    """Neutral conversation-turn shape for commands that read the thread (/ticket)."""

    role: Literal["user", "assistant"]
    content: str


class TranscriptSource(Protocol):
    async def fetch(self) -> list[TranscriptMessage]: ...


class BaseSlashCommand(ABC):
    """Runtime-agnostic command core. Each runtime wraps it with an adapter that resolves the
    context from its own inputs and shapes the output envelope."""

    name: ClassVar[str]  # "/usage"

    def __init__(self, context: SlashCommandContext, transcript_source: Optional[TranscriptSource] = None) -> None:
        self._context = context
        self._transcript_source = transcript_source

    @abstractmethod
    async def execute(self, arg: str) -> str:
        """Run the command and return the assistant reply as markdown."""
        raise NotImplementedError
