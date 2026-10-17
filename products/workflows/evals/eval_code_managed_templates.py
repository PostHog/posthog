"""How PostHog AI changes an email template that is managed by code.

A code-managed template is a file in the person's repository, so PostHog refuses writes to it. PostHog AI runs inside
PostHog Code, where `workflows-request-email-template-change` refuses its calls. So when the template's repository is
not in its workspace, PostHog AI leaves the template alone and links its page, where "Run with PostHog Code" opens the
pull request. A template made in PostHog keeps its normal editing path.

Three cases, one per surface:

* ``sidebar_on_code_managed_page`` — the sidebar on the template's page, with the context the page attaches.
* ``slack_message_names_code_managed_template`` — a Slack message that names the template, with no page context.
* ``gui_template_still_patched`` — the same request on a template made in PostHog.

Every case runs in a sandbox with `posthog/hedgebox` checked out, which is not the template's repository. Two
situations the harness can't build stay unproven here: an agent in the template's repository (it edits the file), and
an agent outside PostHog Code without the repository (it calls the request tool).

To run:
    flox activate -- bash -c "hogli evals eval_code_managed_templates"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.workflows.evals.scorers import (
    DidNotRequestChangeFromPostHogCode,
    EditedGuiTemplate,
    LeftCodeManagedTemplateAlone,
    SharedTemplateLink,
)
from products.workflows.evals.seeders import CODE_MANAGED_TEMPLATE_NAME, GUI_TEMPLATE_NAME, seed_email_templates

CHANGE_REQUEST: Final = "Make the button green."

# The first message the sidebar sends on the code-managed template's page. templateAgentContext.test.ts renders it
# from the page's real context builder and fails when the page changes it.
SIDEBAR_PROMPT: Final = Path(__file__).parent / "fixtures" / "sidebar_on_code_managed_page.txt"
TEMPLATE_ID_PLACEHOLDER: Final = "{code_managed_template_id}"


def sidebar_prompt_on_code_managed_page(seed: dict[str, Any]) -> str:
    return SIDEBAR_PROMPT.read_text().replace(TEMPLATE_ID_PLACEHOLDER, seed["code_managed_template_id"])


async def eval_code_managed_templates(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="sidebar_on_code_managed_page",
            prompt=f"<sidebar context for the {CODE_MANAGED_TEMPLATE_NAME} page>\n\n{CHANGE_REQUEST}",
            prompt_from_seed=sidebar_prompt_on_code_managed_page,
            setup=seed_email_templates,
            expected={"shared_template_link": True},
        ),
        SandboxedEvalCase(
            name="slack_message_names_code_managed_template",
            prompt=f'Can you make the button in our "{CODE_MANAGED_TEMPLATE_NAME}" email template green?',
            interaction_origin="slack",
            setup=seed_email_templates,
            expected={"shared_template_link": True},
        ),
        SandboxedEvalCase(
            name="gui_template_still_patched",
            prompt=f'Can you make the button in our "{GUI_TEMPLATE_NAME}" email template green?',
            setup=seed_email_templates,
            expected={"edited_gui_template": True},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-workflows-code-managed-templates-cli",
        cases=cases,
        scorers=[
            # Every case has to read the template before it can tell who owns it.
            RequiredToolCall({"workflows-get-email-template"}, name="read_the_template"),
            LeftCodeManagedTemplateAlone(),
            DidNotRequestChangeFromPostHogCode(),
            SharedTemplateLink(),
            EditedGuiTemplate(),
        ],
        ctx=ctx,
    )
