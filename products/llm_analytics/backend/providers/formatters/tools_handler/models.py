from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class Tool:
    """Internal representation of a tool/function"""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolFormat(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
