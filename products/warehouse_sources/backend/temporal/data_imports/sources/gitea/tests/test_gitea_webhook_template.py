import hmac
import json
import hashlib
from typing import Any

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.webhook_template import template


class TestGiteaWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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
        inputs: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        return self.run_function(
            {"signing_secret": "", "bypass_signature_check": True, "schema_mapping": schema_mapping, **(inputs or {})},
            globals={
                "request": {
                    "method": "POST",
                    "headers": {"x-gitea-event": event_type, **(extra_headers or {})},
                    "body": body,
                    "stringBody": json.dumps(body),
                    "query": {},
                }
            },
        )

    def test_issues_event_lands_nested_issue_object(self):
        # The 'issues' event nests its object under the singular 'issue' key — the template
        # must remap it or every issue webhook 200-skips and the table silently goes stale.
        issue = {"id": 42, "number": 7, "state": "open", "updated_at": "2026-01-20T10:00:00Z"}
        self._run("issues", {"action": "opened", "number": 7, "issue": issue}, {"issues": "schema_issues"})

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(issue, "schema_issues")

    def test_pull_request_event_lands_nested_object(self):
        pull_request = {"id": 9, "number": 3, "state": "open", "merged": False}
        self._run(
            "pull_request",
            {"action": "opened", "number": 3, "pull_request": pull_request},
            {"pull_request": "schema_prs"},
        )

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(pull_request, "schema_prs")

    def test_unmapped_event_type_no_ops(self):
        # Gitea repos commonly have push/release events enabled too; those must 200-skip.
        res = self._run("push", {"ref": "refs/heads/main"}, {"issues": "schema_issues"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_missing_object_in_payload_is_skipped_with_200(self):
        res = self._run("issues", {"action": "opened"}, {"issues": "schema_issues"})

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_valid_bare_hex_signature_is_accepted(self):
        # Gitea sends the bare hex HMAC (no sha256= prefix, unlike GitHub) — a prefix
        # comparison regression would reject every genuine delivery.
        issue = {"id": 42}
        body = {"action": "opened", "issue": issue}
        signature = hmac.new(b"s3cret", json.dumps(body).encode(), hashlib.sha256).hexdigest()

        self._run(
            "issues",
            body,
            {"issues": "schema_issues"},
            inputs={"signing_secret": "s3cret", "bypass_signature_check": False},
            extra_headers={"x-gitea-signature": signature},
        )

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(issue, "schema_issues")

    def test_bad_signature_is_rejected(self):
        res = self._run(
            "issues",
            {"action": "opened", "issue": {"id": 42}},
            {"issues": "schema_issues"},
            inputs={"signing_secret": "s3cret", "bypass_signature_check": False},
            extra_headers={"x-gitea-signature": "deadbeef"},
        )

        assert res.result["httpResponse"]["status"] == 400
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
