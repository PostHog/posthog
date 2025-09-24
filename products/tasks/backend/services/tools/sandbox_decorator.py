"""
Decorator for executing tools in a sandbox environment.
"""

import functools
from collections.abc import Callable
from typing import Any, Optional

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


def with_sandbox(sandbox: Optional[SandboxEnvironment]):
    """
    Decorator that injects a sandbox environment into tool functions.

    Usage:
        @with_sandbox(sandbox_instance)
        async def my_tool(args: dict[str, Any], sandbox: SandboxEnvironment) -> dict[str, Any]:
            # Tool implementation using sandbox
            pass
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(args: dict[str, Any]) -> dict[str, Any]:
            if not sandbox or not sandbox.is_running:
                return {"content": [{"type": "text", "text": "Error: Sandbox not available"}], "isError": True}
            return await func(args, sandbox)

        return wrapper

    return decorator
