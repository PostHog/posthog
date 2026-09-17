from dataclasses import dataclass

from posthog.schema import AgentMode

from .executables import AgentExecutable, AgentToolsExecutable
from .toolkit import AgentToolkit


@dataclass
class AgentModeDefinition:
    mode: AgentMode
    """The name of the agent's mode."""
    mode_description: str
    """The description of the agent's mode that will be injected into the tool. Keep it short and concise."""
    toolkit_class: type[AgentToolkit] = AgentToolkit
    """A custom toolkit class to use for the agent."""
    node_class: type[AgentExecutable] = AgentExecutable
    """A custom node class to use for the agent."""
    tools_node_class: type[AgentToolsExecutable] = AgentToolsExecutable
    """A custom tools node class to use for the agent."""
