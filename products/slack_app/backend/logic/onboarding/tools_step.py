from products.mcp_store.backend.facade.api import get_active_installations
from products.slack_app.backend.logic.onboarding.actions import CONTINUE_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep, OnboardingStepKey
from products.slack_app.backend.services.slack_messages import project_web_url, section_block


class ToolsStep(OnboardingStep):
    key = OnboardingStepKey.TOOLS
    title = "Your tools"
    done_text = "Tools connected"

    def applies(self, ctx: OnboardingContext) -> bool:
        # MCP servers connect for a PostHog user, so the step needs an account that can link.
        return ctx.can_link

    def is_done(self, ctx: OnboardingContext) -> bool:
        user = ctx.posthog_user
        return user is not None and bool(get_active_installations(ctx.integration.team_id, user.id))

    def render(self, ctx: OnboardingContext) -> list[dict]:
        return [
            section_block(
                "*Connect your tools*\n"
                "I can also use MCP servers, such as Linear or Notion. Connect them in PostHog, and I use them "
                "with your own access. Press Continue when you're done."
            ),
            {
                "type": "actions",
                "elements": [
                    # A URL button: the servers connect in the browser, and the thread updates on Continue.
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Connect an MCP server"},
                        "url": f"{project_web_url(ctx.integration.team_id)}/mcp-servers",
                        "style": "primary",
                    },
                    button(ctx, "Continue", CONTINUE_ACTION_ID, step=self.key),
                    skip_button(ctx, self.key),
                ],
            },
        ]
