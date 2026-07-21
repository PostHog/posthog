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

    def _run(
        self,
        event_type: str,
        body: dict[str, Any],
        schema_mapping: dict[str, str],
        legacy_repository: str | None = None,
    ) -> Any:
        inputs: dict[str, Any] = {
            "signing_secret": "",
            "bypass_signature_check": True,
            "schema_mapping": schema_mapping,
        }
        if legacy_repository is not None:
            inputs["legacy_repository"] = legacy_repository
        return self.run_function(
            inputs,
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

    def test_repo_qualified_mapping_routes_by_repository_full_name(self):
        # Multi-repo sources key the mapping by 'owner/repo.event' — without the qualified lookup
        # two repos' workflow events would all land in whichever schema owns the bare key.
        job = {"id": 1, "status": "completed"}
        body = {"action": "completed", "workflow_job": job, "repository": {"full_name": "Acme/Widgets"}}
        mapping = {"acme/widgets.workflow_job": "schema_widgets_jobs", "workflow_job": "schema_legacy_jobs"}

        self._run("workflow_job", body, mapping)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(job, "schema_widgets_jobs")

    def test_unqualified_repo_falls_back_to_bare_event_mapping(self):
        # Legacy single-repo mappings only carry bare event keys; a payload from any repo must
        # keep routing through them.
        job = {"id": 1, "status": "completed"}
        body = {"action": "completed", "workflow_job": job, "repository": {"full_name": "acme/other"}}

        self._run("workflow_job", body, {"workflow_job": "schema_legacy_jobs"})

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(job, "schema_legacy_jobs")

    def test_unmapped_repo_and_event_no_ops(self):
        body = {"action": "completed", "workflow_job": {"id": 1}, "repository": {"full_name": "acme/unknown"}}
        res = self._run("workflow_job", body, {"acme/widgets.workflow_job": "schema_widgets_jobs"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_bare_key_fallback_is_bound_to_legacy_repository(self):
        # A mixed source keeps the legacy repo's rows on the bare event key and other repos' rows
        # qualified. An event from a secondary repo whose qualified schema is disabled/removed must
        # NOT fall back to the legacy repo's bare key — that would write one repo's data into
        # another repo's schema. With legacy_repository pinned, the fallback is skipped.
        job = {"id": 1, "status": "completed"}
        body = {"action": "completed", "workflow_job": job, "repository": {"full_name": "acme/secondary"}}

        res = self._run("workflow_job", body, {"workflow_job": "schema_legacy_jobs"}, legacy_repository="acme/legacy")

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_legacy_repository_event_still_routes_through_bare_key(self):
        # The legacy repo's own events (its rows stay bare) keep routing through the bare key; the
        # repo comparison is case-insensitive to match GitHub's case-insensitive full names.
        job = {"id": 2, "status": "completed"}
        body = {"action": "completed", "workflow_job": job, "repository": {"full_name": "Acme/Legacy"}}

        self._run("workflow_job", body, {"workflow_job": "schema_legacy_jobs"}, legacy_repository="acme/legacy")

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(job, "schema_legacy_jobs")
