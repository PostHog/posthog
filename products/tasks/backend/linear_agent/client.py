"""Minimal Linear GraphQL client for the PostHog Code Linear agent integration."""

from typing import Any

import requests
import structlog

from posthog.models.integration import Integration, dot_get

logger = structlog.get_logger(__name__)

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
REQUEST_TIMEOUT_SECONDS = 10


class LinearAgentApiError(Exception):
    """The Linear GraphQL API returned a non-200 response or GraphQL-level errors."""


class LinearAgentClient:
    """Wrapper around a ``linear-agent`` Integration row for Linear GraphQL calls.

    Unlike ``LinearIntegration.query`` (which returns raw bodies and leaves error
    handling to callers), every call here raises ``LinearAgentApiError`` on failure so
    Celery tasks can retry on it.
    """

    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "linear-agent":
            raise ValueError("LinearAgentClient requires an Integration of kind 'linear-agent'")
        self.integration = integration

    def organization_id(self) -> str | None:
        return dot_get(self.integration.config, "data.viewer.organization.id")

    def bot_user_id(self) -> str | None:
        return dot_get(self.integration.config, "data.viewer.id")

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = requests.post(
                LINEAR_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
                json={"query": query, "variables": variables or {}},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise LinearAgentApiError(f"Linear API request failed: {e}") from e

        if response.status_code != 200:
            raise LinearAgentApiError(f"Linear API returned status {response.status_code}")

        body: dict[str, Any] = response.json()
        if body.get("errors"):
            raise LinearAgentApiError(f"Linear API returned errors: {body['errors']}")
        return body

    def get_issue_description(self, issue_id: str) -> str | None:
        body = self.query(
            "query Issue($id: String!) { issue(id: $id) { description } }",
            {"id": issue_id},
        )
        return dot_get(body, "data.issue.description")

    def create_comment(self, issue_id: str, body: str) -> None:
        self.query(
            """
            mutation CommentCreate($issueId: String!, $body: String!) {
                commentCreate(input: { issueId: $issueId, body: $body }) { success }
            }
            """,
            {"issueId": issue_id, "body": body},
        )

    def create_agent_activity(self, agent_session_id: str, body: str, *, activity_type: str = "thought") -> None:
        self.query(
            """
            mutation AgentActivityCreate($input: AgentActivityCreateInput!) {
                agentActivityCreate(input: $input) { success }
            }
            """,
            {"input": {"agentSessionId": agent_session_id, "content": {"type": activity_type, "body": body}}},
        )
