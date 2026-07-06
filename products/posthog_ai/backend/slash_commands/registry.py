from pydantic import BaseModel

from products.posthog_ai.backend.slash_commands.base import BaseSlashCommand
from products.posthog_ai.backend.slash_commands.feedback import FeedbackCommand
from products.posthog_ai.backend.slash_commands.ticket import TicketCommand
from products.posthog_ai.backend.slash_commands.usage import UsageCommand

# Sandbox-runtime registry. `/init` and `/remember` stay LangGraph-only (the agent-memory MCP
# toolset is their sandbox story), so they are intentionally absent here.
COMMAND_HANDLERS: dict[str, type[BaseSlashCommand]] = {
    "/usage": UsageCommand,
    "/feedback": FeedbackCommand,
    "/ticket": TicketCommand,
}


class SlashCommandResult(BaseModel):
    """HTTP response body for a slash command executed server-side by `ConversationViewSet.open`.
    The `type` discriminant distinguishes it from the run-handle body returned for a normal turn."""

    type: str = "slash_command"
    command: str
    content: str
    trace_id: str | None = None


def match_slash_command(content: str) -> tuple[type[BaseSlashCommand], str] | None:
    """Detect a registered slash command in `content`, returning its handler class and the argument
    text after the command. Exact-or-`prefix + " "` matching, mirroring the LangGraph
    `SlashCommandHandlerNode._get_command`. Returns None for plain text and unregistered `/foo`."""
    stripped = content.strip()
    for command, handler in COMMAND_HANDLERS.items():
        if stripped == command:
            return handler, ""
        if stripped.startswith(command + " "):
            return handler, stripped[len(command) :].strip()
    return None
