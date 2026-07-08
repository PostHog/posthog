from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import (
    CodeHomeDTO,
    CodeHomeWorkstreamDTO,
    CodeWorkflowConfigDTO,
    CodeWorkflowDiagnosticDTO,
)

_AUTH_CLASSES = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]


def _serialize_diagnostic(d: CodeWorkflowDiagnosticDTO) -> dict:
    out = {"severity": d.severity, "code": d.code, "message": d.message}
    if d.situation_id is not None:
        out["situationId"] = d.situation_id
    if d.action_id is not None:
        out["actionId"] = d.action_id
    return out


def _serialize_config(config: CodeWorkflowConfigDTO) -> dict:
    return {
        "id": config.id,
        "version": config.version,
        "updatedAt": config.updated_at.isoformat(),
        "bindings": config.bindings,
    }


def _serialize_home(home: CodeHomeDTO) -> dict:
    return {
        "activeAgents": [
            {
                "taskId": agent.task_id,
                "title": agent.title,
                "repoName": agent.repo_name,
                "branch": agent.branch,
                "status": agent.status,
                "lastActivityAt": agent.last_activity_at,
                "needsPermission": agent.needs_permission,
                "cloudPrUrl": agent.cloud_pr_url,
            }
            for agent in home.active_agents
        ],
        "needsAttention": [_serialize_workstream(ws) for ws in home.needs_attention],
        "inProgress": [_serialize_workstream(ws) for ws in home.in_progress],
    }


def _serialize_workstream(ws: CodeHomeWorkstreamDTO) -> dict:
    return {
        "id": ws.id,
        "repoName": ws.repo_name,
        "repoFullPath": ws.repo_full_path,
        "branch": ws.branch,
        "prUrl": ws.pr_url,
        "pr": ws.pr,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "isGenerating": t.is_generating,
                "needsPermission": t.needs_permission,
                "quickAction": t.quick_action,
            }
            for t in ws.tasks
        ],
        "situations": ws.situations,
        "primarySituation": ws.primary_situation,
        "lastActivityAt": ws.last_activity_at,
    }


class CodeWorkflowViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [IsAuthenticated, APIScopePermission]
    hide_api_docs = True

    def list(self, request, *args, **kwargs):
        config = tasks_facade.get_code_workflow_config(self.team_id, request.user.id)
        return Response(_serialize_config(config))

    @action(detail=False, methods=["post"], url_path="save", required_scopes=["task:write"])
    def save(self, request, **kwargs):
        config_in = request.data.get("config") or {}
        expected_version = request.data.get("expectedVersion")
        bindings = config_in.get("bindings") or {}

        result = tasks_facade.save_code_workflow_bindings(
            self.team_id,
            request.user.id,
            bindings=bindings,
            expected_version=expected_version,
        )

        if result.outcome == tasks_facade.CODE_WORKFLOW_CONFLICT:
            return Response(
                {"status": "conflict", "config": _serialize_config(result.config)},
                status=status.HTTP_409_CONFLICT,
            )
        if result.outcome == tasks_facade.CODE_WORKFLOW_INVALID:
            return Response(
                {
                    "status": "invalid",
                    "config": _serialize_config(result.config),
                    "diagnostics": [_serialize_diagnostic(d) for d in result.diagnostics],
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response({"status": "saved", "config": _serialize_config(result.config)})

    @action(detail=False, methods=["post"], url_path="reset", required_scopes=["task:write"])
    def reset(self, request, **kwargs):
        config = tasks_facade.reset_code_workflow_bindings(self.team_id, request.user.id)
        return Response(_serialize_config(config))


class CodeHomeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [IsAuthenticated, APIScopePermission]
    hide_api_docs = True

    def list(self, request, *args, **kwargs):
        return Response(_serialize_home(tasks_facade.get_code_home(self.team_id, request.user.id)))

    @action(detail=False, methods=["post"], url_path="refresh", required_scopes=["task:write"])
    def refresh(self, request, **kwargs):
        started = tasks_facade.refresh_team_code_workstreams(self.team_id)
        return Response({"started": started}, status=status.HTTP_202_ACCEPTED)
