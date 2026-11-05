from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey, OnboardingStepSpec
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_user_oauth import build_invite_url


def _applies(ctx: OnboardingContext) -> bool:
    return is_slack_app_oauth_enabled(ctx.integration)


def _is_done(ctx: OnboardingContext) -> bool:
    return ctx.posthog_user is not None


def _render(ctx: OnboardingContext) -> list[dict]:
    link_url = build_invite_url(
        slack_user_id=ctx.slack_user_id,
        slack_team_id=ctx.integration.integration_id,
        posthog_team_id=ctx.integration.team_id,
        channel=None,
        thread_ts=None,
    )
    return [
        section_block(
            "*Link your PostHog account*\n"
            "PostHog answers you in Slack from your projects, with the access you have in PostHog."
        ),
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


LINK_ACCOUNT_STEP = OnboardingStepSpec(
    key=OnboardingStepKey.LINK_ACCOUNT,
    title="Link your PostHog account",
    done_text="PostHog account linked",
    skippable=False,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
