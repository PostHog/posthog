from products.slack_app.backend.logic.onboarding.actions import CONTINUE_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.checks import has_personal_github, has_team_github
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep, OnboardingStepKey
from products.slack_app.backend.services.slack_messages import personal_integrations_url, section_block
from products.slack_app.backend.services.slack_welcome_messages import github_connect_button
from products.tasks.backend.facade.api import user_has_usable_personal_github


class GithubStep(OnboardingStep):
    key = OnboardingStepKey.GITHUB
    title = "GitHub"
    done_text = "GitHub connected"
    completed_by_continue = True

    def applies(self, ctx: OnboardingContext) -> bool:
        # A member's personal GitHub only helps once the team has the GitHub app, which an admin installs.
        return ctx.can_link and (ctx.is_workspace_admin or has_team_github(ctx.integration.team_id))

    def is_done(self, ctx: OnboardingContext) -> bool:
        # An expired connection cannot open pull requests, so it does not count as done. The task flow uses the same
        # check before a run, so onboarding and tasks agree on an expired token.
        user = ctx.posthog_user
        return (
            user is not None and user_has_usable_personal_github(user.id) and has_team_github(ctx.integration.team_id)
        )

    def needs_reconnect(self, ctx: OnboardingContext) -> bool:
        user = ctx.posthog_user
        return user is not None and has_personal_github(user.id) and not user_has_usable_personal_github(user.id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        if self.needs_reconnect(ctx):
            text = (
                "*Reconnect GitHub*\nYour GitHub access expired, so I can't open pull requests as you. "
                "Reconnect it in PostHog, then press Continue."
            )
            # Reconnecting needs a PostHog session, so the button opens the same settings page as the Home tab.
            connect = {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reconnect GitHub"},
                "url": personal_integrations_url(ctx.integration.team_id),
                "style": "primary",
            }
        else:
            text = (
                "*Connect GitHub*\nWhen I find a problem, I can open a pull request with the fix for you to review. "
                "Press Continue when GitHub is connected."
            )
            connect = github_connect_button(ctx.integration.team_id)
        return [
            section_block(text),
            {
                "type": "actions",
                "elements": [
                    connect,
                    # GitHub tells Slack nothing when the connection finishes, so the person moves the thread on.
                    button(ctx, "Continue", CONTINUE_ACTION_ID, step=self.key),
                    skip_button(ctx, self.key),
                ],
            },
        ]
