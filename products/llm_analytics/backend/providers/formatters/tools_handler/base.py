from abc import ABC, abstractmethod
from typing import Any

from .models import Tool


class ToolFormatter(ABC):
    """Abstract base class for tool format parsers and serializers"""

    @abstractmethod
    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        """Check if this formatter can parse the given tool data"""
        pass

    @abstractmethod
    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        """Parse tool data into internal Tool objects"""
        pass

    @abstractmethod
    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        """Serialize Tool objects into format-specific data"""
        pass
