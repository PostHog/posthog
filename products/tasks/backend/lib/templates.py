from typing import Optional

from pydantic import BaseModel


class WorkflowTemplate(BaseModel):
    name: str
    description: str
    stages: list["WorkflowStageTemplate"]


class WorkflowStageTemplate(BaseModel):
    key: str
    name: str
    color: str
    agent_name: Optional[str]
    is_manual_only: bool = False


DEFAULT_WORKFLOW_STAGES: list[WorkflowStageTemplate] = [
    WorkflowStageTemplate(key="backlog", name="Backlog", color="#6b7280", agent_name=None),
    WorkflowStageTemplate(key="todo", name="Todo", color="#3b82f6", agent_name=None),
    WorkflowStageTemplate(key="in_progress", name="In Progress", color="#f59e0b", agent_name="code_generation"),
    WorkflowStageTemplate(key="testing", name="Testing", color="#8b5cf6", agent_name="code_generation"),
    WorkflowStageTemplate(key="done", name="Done", color="#10b981", agent_name=None),
]

DEFAULT_WORKFLOW_TEMPLATE = WorkflowTemplate(
    name="Default Code Generation Workflow",
    description="Default workflow for code generation tasks",
    stages=DEFAULT_WORKFLOW_STAGES,
)
