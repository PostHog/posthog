from __future__ import annotations

import inspect
import importlib
from typing import TYPE_CHECKING, Any, cast

from products.signals.backend.custom_agent.schemas import validate_identifier, validated_identifier

if TYPE_CHECKING:
    from products.signals.backend.custom_agent.base import CustomSignalAgent


class CustomAgentLoadError(RuntimeError):
    """Raised when a custom signal agent class cannot be imported or validated."""


def import_agent_class(agent_path: str) -> type[CustomSignalAgent]:
    """Import a CustomSignalAgent subclass from a dotted `module.ClassName` path."""
    if not isinstance(agent_path, str) or not agent_path.strip():
        raise CustomAgentLoadError("agent_path must be a non-empty dotted import path")

    module_path, separator, class_name = agent_path.strip().rpartition(".")
    if not separator or not module_path or not class_name:
        raise CustomAgentLoadError(f"Invalid agent_path {agent_path!r}; expected 'module.ClassName'")
    if "." in class_name:
        raise CustomAgentLoadError("agent_path must point to a top-level class")

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise CustomAgentLoadError(f"Could not import custom signal agent module {module_path!r}") from exc

    try:
        imported: Any = getattr(module, class_name)
    except AttributeError as exc:
        raise CustomAgentLoadError(f"Module {module_path!r} has no attribute {class_name!r}") from exc

    if not inspect.isclass(imported):
        raise CustomAgentLoadError(f"Object at {agent_path!r} is not a class")

    from products.signals.backend.custom_agent.base import CustomSignalAgent

    if not issubclass(imported, CustomSignalAgent):
        raise CustomAgentLoadError(f"Class at {agent_path!r} is not a CustomSignalAgent subclass")
    if imported is CustomSignalAgent:
        raise CustomAgentLoadError("CustomSignalAgent base class cannot be started directly")
    return cast("type[CustomSignalAgent]", imported)


def validate_agent_class_identity(agent_class: type[CustomSignalAgent], product: str, type_: str) -> tuple[str, str]:
    """Validate that an imported class matches the workflow input identity."""
    expected = validate_identifier(product, type_)
    actual = validated_identifier(agent_class)
    if actual != expected:
        raise CustomAgentLoadError(
            f"Custom signal agent identity mismatch: workflow requested {expected!r}, "
            f"but {agent_class.__module__}.{agent_class.__qualname__} returned {actual!r}"
        )
    return actual
