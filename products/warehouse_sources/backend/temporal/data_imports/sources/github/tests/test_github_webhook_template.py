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


_COMMIT_SHA = "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736"


def _status_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": 4100,
        "sha": _COMMIT_SHA,
        "name": "acme/widgets",
        "node_id": "SE_fakecommitstatusnode",
        "state": "success",
        "description": "Build passed",
        "target_url": "https://ci.example.com/builds/4100",
        "context": "ci/build",
        "avatar_url": "https://avatars.example.com/u/12",
        "created_at": "2026-02-01T09:00:00Z",
        "updated_at": "2026-02-01T09:00:30Z",
        "commit": {"sha": _COMMIT_SHA, "url": "https://api.example.com/repos/acme/widgets/commits/0f1e2d3c"},
        "branches": [{"name": "main"}],
        "repository": {"full_name": "acme/widgets"},
        "sender": {"login": "ci-bot"},
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

    @parameterized.expand(
        [
            ("workflow_job", "completed", {"id": 1, "status": "completed", "conclusion": "success"}),
            ("deployment", "created", {"id": 7, "environment": "production", "sha": "abc123"}),
            (
                "check_run",
                "completed",
                {"id": 42, "head_sha": "abc123", "status": "completed", "conclusion": "success"},
            ),
        ]
    )
    def test_row_lands_unchanged_when_event_nests_under_its_own_key(
        self, event_type: str, action: str, obj: dict[str, Any]
    ):
        # These events nest the object under body.<event_type>, matching the polled REST shape, so
        # the row lands as-is. check_run is the one that could regress silently: it is a per-commit
        # fan-out child, and if it ever started injecting a parent column the way reviews and
        # deployment_statuses do, webhook rows would drift from poll rows without erroring.
        self._run(event_type, {"action": action, event_type: obj}, {event_type: "schema_x"})

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(obj, "schema_x")

    def test_deployment_status_row_is_reshaped_to_poll_shape(self):
        # The deployment_status event nests the status under body.deployment_status and its
        # deployment under body.deployment; the status carries no deployment_id. The template must
        # inject deployment_id so webhook rows match poll rows (which carry it from the parent).
        body = {
            "action": "created",
            "deployment_status": {"id": 900, "state": "success", "created_at": "2026-01-20T10:00:00Z"},
            "deployment": {"id": 7, "environment": "production"},
        }
        self._run("deployment_status", body, {"deployment_status": "schema_statuses"})

        row, schema_id = self.mock_produce_to_warehouse_webhooks.call_args.args
        assert schema_id == "schema_statuses"
        assert row["id"] == 900
        assert row["state"] == "success"
        assert row["deployment_id"] == 7

    @parameterized.expand(
        [
            ("missing_status", {"action": "created", "deployment": {"id": 7}}),
            ("missing_deployment", {"action": "created", "deployment_status": {"id": 900, "state": "success"}}),
        ]
    )
    def test_incomplete_deployment_status_payload_is_skipped_with_200(self, _name: str, body: dict[str, Any]):
        res = self._run("deployment_status", body, {"deployment_status": "schema_statuses"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_status_row_is_rebuilt_from_top_level_body_fields(self):
        # The status event has no nesting key: its fields sit at the top level of the body next to
        # commit/repository/sender/branches envelope objects and a `name` holding the repository.
        # Without the rebuild the row is either empty (there is no body.status) or carries envelope
        # columns the poll never writes, and commit_sha stays null even though it is the first half
        # of the table's composite primary key, so every later merge multi-matches.
        self._run("status", _status_body(), {"status": "schema_commit_statuses"})

        row, schema_id = self.mock_produce_to_warehouse_webhooks.call_args.args
        assert schema_id == "schema_commit_statuses"
        assert row == {
            "id": 4100,
            "node_id": "SE_fakecommitstatusnode",
            "state": "success",
            "description": "Build passed",
            "target_url": "https://ci.example.com/builds/4100",
            "context": "ci/build",
            "avatar_url": "https://avatars.example.com/u/12",
            "creator": {"login": "ci-bot"},
            "created_at": "2026-02-01T09:00:00Z",
            "updated_at": "2026-02-01T09:00:30Z",
            "commit_sha": _COMMIT_SHA,
        }

    @parameterized.expand(
        [
            ("missing_id", {"sha": _COMMIT_SHA, "state": "success"}),
            ("missing_sha", {"id": 4100, "state": "success"}),
        ]
    )
    def test_status_payload_without_id_or_sha_is_skipped_with_200(self, _name: str, body: dict[str, Any]):
        # The rebuilt row is a non-empty dict whatever the payload holds, so the shared empty-row
        # guard below it never fires; without this check a status missing either half of the
        # composite key would land a row the merge can't match.
        res = self._run("status", body, {"status": "schema_commit_statuses"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("issue_comment", {"id": 7010, "body": "Looks good", "issue_url": "https://api.example.com/issues/3"}),
            (
                "pull_request_review_comment",
                {"id": 7011, "body": "Rename this", "path": "src/app.py", "pull_request_review_id": 55},
            ),
            ("commit_comment", {"id": 7012, "body": "Nice fix", "commit_id": _COMMIT_SHA}),
        ]
    )
    def test_comment_events_land_the_nested_comment_object(self, event_type: str, comment: dict[str, Any]):
        # All three comment events nest the row under `comment` rather than the event-type key, so
        # without the unwrap branch the default lookup finds nothing and every comment delivery
        # 200-skips: the table silently keeps only whatever the bootstrap poll left behind.
        body = {"action": "created", "comment": comment, "repository": {"full_name": "acme/widgets"}}

        self._run(event_type, body, {event_type: "schema_comments"})

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(comment, "schema_comments")

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
