from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.posthog_ai.eval_harness.scorers.contract import Scorer
from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.workflows.evals.eval_code_managed_templates import sidebar_prompt_on_code_managed_page
from products.workflows.evals.scorers import (
    DidNotRequestChangeFromPostHogCode,
    EditedGuiTemplate,
    LeftCodeManagedTemplateAlone,
)
from products.workflows.evals.seeders import seed_email_templates

SEED = {"code_managed_template_id": "code-1", "gui_template_id": "gui-1"}
PATCH = "workflows-patch-email-template"
REQUEST = "workflows-request-email-template-change"


@pytest.mark.parametrize(
    "scorer,calls,expected_score",
    [
        # The lock refuses the write, so only counting attempts shows the agent tried it.
        (LeftCodeManagedTemplateAlone(), [(PATCH, {"id": "code-1"}, "403 immutable", "failed")], 0.0),
        (LeftCodeManagedTemplateAlone(), [(PATCH, {"id": "gui-1"}, "ok")], 1.0),
        # An upload by the key publishes HTML rebuilt from PostHog, which the file doesn't have.
        (LeftCodeManagedTemplateAlone(), [("workflows-upload-email-template", {"key": "hedgebox-welcome"}, "ok")], 0.0),
        (LeftCodeManagedTemplateAlone(), [("workflows-get-email-template", {"id": "code-1"}, "ok")], 1.0),
        # The route refuses calls from inside PostHog Code, so a refused call is the wrong choice too.
        (
            DidNotRequestChangeFromPostHogCode(),
            [(REQUEST, {"id": "code-1"}, "posthog_code_not_available", "failed")],
            0.0,
        ),
        (DidNotRequestChangeFromPostHogCode(), [(PATCH, {"id": "gui-1"}, "ok")], 1.0),
        (EditedGuiTemplate(), [(PATCH, {"id": "gui-1"}, "bad operation", "failed")], 0.0),
        (EditedGuiTemplate(), [(PATCH, {"id": "gui-1"}, "ok")], 1.0),
    ],
)
def test_code_managed_template_scorers(scorer: Scorer, calls: Sequence[tuple[Any, ...]], expected_score: float) -> None:
    score = scorer._run_eval_sync({"raw_log": _raw_tool_log(calls), "seed": SEED}, {"edited_gui_template": True})

    assert score.score == expected_score


class TestCodeManagedTemplateSeeder(APIBaseTest):
    @patch("products.messaging.backend.presentation.views.message_templates.render_design_html", return_value="<html/>")
    def test_seeds_one_template_per_owner_that_the_cases_can_reach(self, _render: Any) -> None:
        seed = seed_email_templates(CustomPromptSandboxContext(team_id=self.team.id, user_id=self.user.id))
        templates = f"/api/projects/{self.team.id}/messaging_templates"

        code_managed = self.client.get(f"{templates}/{seed['code_managed_template_id']}/").json()
        assert {key: code_managed[key] for key in ("managed_by", "key", "source_path")} == {
            "managed_by": "code",
            "key": "hedgebox-welcome",
            "source_path": "emails/welcome.html",
        }
        assert code_managed["change_prompt_context"]
        sidebar_prompt = sidebar_prompt_on_code_managed_page(seed)
        assert f'- email_template {seed["code_managed_template_id"]} ("{code_managed["name"]}")' in sidebar_prompt
        assert (
            f"key: {code_managed['key']}; source_repository: {code_managed['source_repository']}; "
            f"source_path: {code_managed['source_path']}; source_ref: {code_managed['source_ref']}"
        ) in sidebar_prompt

        make_the_button_green = self.client.patch(
            f"{templates}/{seed['gui_template_id']}/design/",
            data={
                "operations": [
                    {
                        "op": "update_content",
                        "id": "btn1",
                        "patch": {"values": {"buttonColors": {"color": "#FFFFFF", "backgroundColor": "#16A34A"}}},
                    }
                ]
            },
            format="json",
        )
        assert make_the_button_green.status_code == status.HTTP_200_OK, make_the_button_green.json()
