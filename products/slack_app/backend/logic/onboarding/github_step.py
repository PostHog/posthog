from products.slack_app.backend.logic.onboarding.actions import skip_button
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep, OnboardingStepKey
from products.slack_app.backend.services.onboarding_checks import has_personal_github, has_team_github
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_welcome_messages import github_connect_url


class GithubStep(OnboardingStep):
    key = OnboardingStepKey.GITHUB
    title = "GitHub"
    done_text = "GitHub connected"

    def applies(self, ctx: OnboardingContext) -> bool:
        # A member's personal GitHub only helps once the team has the GitHub app, which an admin installs.
        return ctx.can_link and (ctx.is_workspace_admin or has_team_github(ctx.integration.team_id))

    def is_done(self, ctx: OnboardingContext) -> bool:
        user = ctx.posthog_user
        return user is not None and has_personal_github(user.id) and has_team_github(ctx.integration.team_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        return [
            section_block(
                "*Connect GitHub*\nThen I can fix things, not only flag them: I open a pull request with the fix "
                "for you to review."
            ),
            {
                "type": "actions",
                "elements": [
                    # A URL button: GitHub connects in the browser, and the thread updates when you come back.
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Connect GitHub"},
                        "url": github_connect_url(ctx.integration.team_id),
                        "style": "primary",
                    },
                    skip_button(ctx, self.key),
                ],
            },
        ]
