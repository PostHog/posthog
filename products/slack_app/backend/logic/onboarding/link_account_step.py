from products.slack_app.backend.feature_flags import (
    is_slack_app_daily_work_focus_enabled,
    is_slack_app_link_search_scopes_enabled,
    is_slack_app_oauth_enabled,
)
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep, OnboardingStepKey
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_user_oauth import build_invite_url


class LinkAccountStep(OnboardingStep):
    key = OnboardingStepKey.LINK_ACCOUNT
    title = "Link your PostHog account"
    done_text = "PostHog account linked"
    skippable = False

    def applies(self, ctx: OnboardingContext) -> bool:
        return is_slack_app_oauth_enabled(ctx.integration)

    def is_done(self, ctx: OnboardingContext) -> bool:
        return ctx.posthog_user is not None

    def render(self, ctx: OnboardingContext) -> list[dict]:
        link_url = build_invite_url(
            slack_user_id=ctx.slack_user_id,
            slack_team_id=ctx.integration.integration_id,
            posthog_team_id=ctx.integration.team_id,
            channel=None,
            thread_ts=None,
        )
        text = "*Link your PostHog account*\nPostHog answers you in Slack from your projects, with the access you have in PostHog."
        if is_slack_app_link_search_scopes_enabled(ctx.integration):
            if is_slack_app_daily_work_focus_enabled(ctx.integration):
                text += (
                    "\nAfter you link, I read your recent Slack messages and suggest what I can help with, then do it "
                    "again each workday morning. You can turn that off in the Home tab. "
                )
            else:
                text += "\nAfter you link, I read your recent Slack messages once to suggest what I can help with. "
            text += "Slack lets you choose which kinds of conversations I can search."
        return [
            section_block(text),
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Link account"},
                        "style": "primary",
                        "url": link_url,
                    }
                ],
            },
        ]
