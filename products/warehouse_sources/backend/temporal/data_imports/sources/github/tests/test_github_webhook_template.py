import json
from typing import Any

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.github.webhook_template import template


def _review_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "action": "submitted",
        "review": {
            "id": 500,
            "state": "approved",
            "submitted_at": "2026-01-20T10:00:00Z",
            "user": {"login": "ada"},
        },
        "pull_request": {"number": 10, "title": "Fix layout"},
    }
    body.update(overrides)
    return body


class TestGithubWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data: dict = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {},
                "query": {},
                "stringBody": "",
                "ip": "127.0.0.1",
            },
        }
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _run(self, event_type: str, body: dict[str, Any], schema_mapping: dict[str, str]) -> Any:
        return self.run_function(
            {"signing_secret": "", "bypass_signature_check": True, "schema_mapping": schema_mapping},
            globals={
                "request": {
                    "method": "POST",
                    "headers": {"x-github-event": event_type},
                    "body": body,
                    "stringBody": json.dumps(body),
                    "query": {},
                }
            },
        )

    def test_pull_request_review_row_is_reshaped_to_poll_shape(self):
        # The review event nests the object under body.review (not the event-type key), uses
        # lowercase states, and carries no PR number on the review itself. The template must
        # reshape it to the polled REST shape or webhook rows diverge from poll rows in the table.
        self._run("pull_request_review", _review_body(), {"pull_request_review": "schema_reviews"})

        row, schema_id = self.mock_produce_to_warehouse_webhooks.call_args.args
        assert schema_id == "schema_reviews"
        assert row["id"] == 500
        assert row["state"] == "APPROVED"
        assert row["pr_number"] == 10
        assert row["submitted_at"] == "2026-01-20T10:00:00Z"
        assert row["user"] == {"login": "ada"}

    @parameterized.expand(
        [
            ("no_submitted_at", _review_body(review={"id": 500, "state": "pending", "submitted_at": None})),
            ("missing_review", {"action": "submitted", "pull_request": {"number": 10}}),
            ("missing_pull_request", {"action": "submitted", "review": {"id": 500, "state": "approved"}}),
        ]
    )
    def test_incomplete_review_payload_is_skipped_with_200(self, _name: str, body: dict[str, Any]):
        res = self._run("pull_request_review", body, {"pull_request_review": "schema_reviews"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_workflow_job_row_lands_unchanged(self):
        job = {"id": 1, "status": "completed", "conclusion": "success"}
        self._run("workflow_job", {"action": "completed", "workflow_job": job}, {"workflow_job": "schema_jobs"})

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(job, "schema_jobs")

    def test_unmapped_event_type_no_ops(self):
        # Sources whose schema_mapping predates the pull_request_review entry must 200-skip the
        # event, not error, so enabling the webhook event repo-wide is safe for old deployments.
        res = self._run("pull_request_review", _review_body(), {"workflow_job": "schema_jobs"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
