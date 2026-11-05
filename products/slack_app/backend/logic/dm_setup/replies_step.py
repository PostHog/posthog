from products.slack_app.backend.logic.dm_setup.actions import REPLIES_ACTION_ID, action_value, skip_button
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep, DmSetupStepKey
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.slack_app_home import UNTAGGED_FOLLOWUP_MODE_LABELS
from products.slack_app.backend.services.slack_settings import has_chosen_untagged_followup_mode


def _applies(_: DmSetupContext) -> bool:
    return True


def _is_done(ctx: DmSetupContext) -> bool:
    return has_chosen_untagged_followup_mode(ctx.integration.integration_id, ctx.slack_user_id)


def _render(ctx: DmSetupContext) -> list[dict]:
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": UNTAGGED_FOLLOWUP_MODE_LABELS[mode]},
            "action_id": f"{REPLIES_ACTION_ID}:{mode}",
            "value": action_value(ctx, mode=mode),
        }
        for mode in (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.ASK, UntaggedFollowupMode.NEVER)
    ]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Replies in threads you start*\n"
                "When someone replies in a thread you started and doesn't tag @PostHog, what should PostHog do? "
                "This applies to your own replies too.",
            },
        },
        {"type": "actions", "elements": [*buttons, skip_button(ctx, DmSetupStepKey.REPLIES_IN_THREADS)]},
    ]


REPLIES_IN_THREADS_STEP = DmSetupStep(
    key=DmSetupStepKey.REPLIES_IN_THREADS,
    title="Replies in threads",
    done_text="Replies in threads set",
    skippable=True,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
