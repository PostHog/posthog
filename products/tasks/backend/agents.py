"""Agent definitions for the Tasks product."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Agent:
    """Represents an agent definition."""

    id: str
    name: str
    agent_type: str
    description: str
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert agent to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "agent_type": self.agent_type,
            "description": self.description,
            "config": self.config,
            "is_active": True,  # All agents are active
        }


# Define all available agents
AGENTS = [
    Agent(
        id="code_generation",
        name="Code Generation Agent",
        agent_type="code_generation",
        description="Automated code generation and GitHub integration",
    ),
    Agent(
        id="triage",
        name="Triage Agent",
        agent_type="triage",
        description="Automatically triages and categorizes tasks based on content",
    ),
    Agent(
        id="review",
        name="Review Agent",
        agent_type="review",
        description="Reviews code changes and provides automated feedback",
    ),
    Agent(
        id="testing",
        name="Testing Agent",
        agent_type="testing",
        description="Runs tests and validates implementation",
    ),
]

# Create lookup dictionaries
AGENTS_BY_ID: dict[str, Agent] = {agent.id: agent for agent in AGENTS}


def get_all_agents() -> list[dict]:
    """Get all agents as serialized dictionaries."""
    return [agent.to_dict() for agent in AGENTS]


def get_agent_by_id(agent_id: str) -> Optional[Agent]:
    """Get a specific agent by ID."""
    return AGENTS_BY_ID.get(agent_id)


def get_agent_dict_by_id(agent_id: str) -> Optional[dict]:
    """Get a specific agent as a dictionary by ID."""
    agent = get_agent_by_id(agent_id)
    return agent.to_dict() if agent else None
