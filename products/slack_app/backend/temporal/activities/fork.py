from temporalio import activity

from products.slack_app.backend.temporal.types import SlackAppForkThreadInputs


@activity.defn
def process_slack_app_fork_thread_activity(inputs: SlackAppForkThreadInputs) -> None:
    from products.slack_app.backend.logic.fork.start import start_fork

    start_fork(inputs.payload, target_channel=inputs.target_channel)
