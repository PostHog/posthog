"""
Facade re-exports for the tasks Max tools.

These ``MaxTool`` subclasses are registered into the Max AI toolkit by core. They cross the
boundary as classes (registry wiring); each tool's implementation stays inside the product.
"""

from products.tasks.backend.max_tools import (
    CreateTaskTool,
    GetTaskRunLogsTool,
    GetTaskRunTool,
    ListRepositoriesTool,
    ListTaskRunsTool,
    ListTasksTool,
    RunTaskTool,
)

__all__ = [
    "CreateTaskTool",
    "GetTaskRunLogsTool",
    "GetTaskRunTool",
    "ListRepositoriesTool",
    "ListTaskRunsTool",
    "ListTasksTool",
    "RunTaskTool",
]
