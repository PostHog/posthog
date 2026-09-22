import re
from pathlib import Path

from django.conf import settings

import yaml

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX
from products.tasks.backend.presentation.serializers import TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES

TASKS_MCP_CONFIG = Path(__file__).resolve().parents[3] / "tasks" / "mcp" / "tools.yaml"


def test_exec_permission_regex_only_matches_connected_project_tools():
    pattern = re.compile(POSTHOG_EXEC_PERMISSION_REGEX, re.IGNORECASE)

    assert pattern.search("posthog-connection-call")
    assert pattern.search("posthog-connection-forward")
    assert not pattern.search("feature-flag-delete")


def test_inline_artifact_ceiling_stays_reachable_through_the_request_body_limit():
    # Django raises RequestDataTooBig before the serializer runs, so an inline ceiling that base64
    # inflates past DATA_UPLOAD_MAX_MEMORY_SIZE turns the "use prepare_upload" error into an opaque
    # 400 with no field attached. Raising this ceiling means raising the body limit with it.
    largest_encoded_body = TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES * 4 // 3

    assert largest_encoded_body < settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def test_task_mcp_tools_can_start_runs():
    tools = yaml.safe_load(TASKS_MCP_CONFIG.read_text())["tools"]

    assert not {"start_run", "branch"}.intersection(tools["tasks-create"]["include_params"])
    assert tools["tasks-create-and-run"]["input_schema"] == "TaskAgentCreateSchema"
    assert tools["tasks-create-and-run"]["feature_flag"] == tools["tasks-run-create"]["feature_flag"]
    assert tools["tasks-run-create"]["enabled"] is True
    assert tools["tasks-run-create"]["input_schema"] == "TaskAgentRunCreateSchema"
