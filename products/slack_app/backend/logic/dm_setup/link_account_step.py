from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep, DmSetupStepKey
from products.slack_app.backend.services.slack_user_oauth import build_invite_url, find_linked_posthog_user
from products.slack_app.backend.services.workspace_integrations import workspace_integrations


def _applies(ctx: DmSetupContext) -> bool:
    return is_slack_app_oauth_enabled(ctx.integration)


def _is_done(ctx: DmSetupContext) -> bool:
    # The same check App Home uses, so the card and the Home tab agree on who is linked.
    slack_team_id = ctx.integration.integration_id
    org_ids = {row.team.organization_id for row in workspace_integrations(slack_team_id)}
    linked = find_linked_posthog_user(
        slack_user_id=ctx.slack_user_id, slack_team_id=slack_team_id, candidate_org_ids=org_ids
    )
    return linked is not None


def _render(ctx: DmSetupContext) -> list[dict]:
    # The invite expires after 15 minutes, so the card gets a new one each time the person opens the DM.
    link_url = build_invite_url(
        slack_user_id=ctx.slack_user_id,
        slack_team_id=ctx.integration.integration_id,
        posthog_team_id=ctx.integration.team_id,
        channel=None,
        thread_ts=None,
    )
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Link your PostHog account*\n"
                "PostHog answers you in Slack from your projects, with the access you have in PostHog.",
            },
        },
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


LINK_ACCOUNT_STEP = DmSetupStep(
    key=DmSetupStepKey.LINK_ACCOUNT,
    title="Link your PostHog account",
    done_text="PostHog account linked",
    skippable=False,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
