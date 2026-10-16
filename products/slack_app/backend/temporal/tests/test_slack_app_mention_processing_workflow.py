import pytest
from unittest.mock import patch

from products.slack_app.backend.temporal import slack_app_mention_processing
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expect_classifier",
    [
        # File-only replies skip the classifier so the attachment isn't dropped.
        ("", False),
        # Replies with text still face the classifier even when files are attached.
        ("nice weather today", True),
    ],
)
async def test_untagged_followup_with_files_classifier_gating(text: str, expect_classifier: bool) -> None:
    workflow = slack_app_mention_processing.SlackAppMentionProcessingWorkflow()
    calls: list[str] = []
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": text,
            "files": [{"id": "F123", "name": "debug.log"}],
        },
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
        untagged_followup=True,
    )

    async def fake_execute_activity(activity_fn, *args):
        calls.append(activity_fn.__name__)
        if activity_fn is slack_app_mention_processing.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is slack_app_mention_processing.classify_untagged_followup_activity:
            return True
        if activity_fn is slack_app_mention_processing.request_untagged_followup_confirmation_activity:
            return False
        if activity_fn is slack_app_mention_processing.classify_slack_app_model_override_activity:
            return None
        if activity_fn is slack_app_mention_processing.forward_posthog_code_followup_activity:
            return True

        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with patch.object(
        slack_app_mention_processing, "_execute_posthog_code_activity", side_effect=fake_execute_activity
    ):
        await workflow.run(inputs)

    expected = ["enforce_posthog_code_billing_quota_activity"]
    if expect_classifier:
        expected.append("classify_untagged_followup_activity")
    expected += [
        "request_untagged_followup_confirmation_activity",
        # The model-override classifier sits above the follow-up/new-task split, so it
        # runs for a reply too.
        "classify_slack_app_model_override_activity",
        "forward_posthog_code_followup_activity",
    ]
    assert calls == expected


@pytest.mark.asyncio
async def test_confirmed_untagged_followup_skips_the_classifier_and_the_prompt() -> None:
    """The click that re-dispatches carries the answer, so asking again would
    loop: prompt, confirm, classify, prompt."""
    workflow = slack_app_mention_processing.SlackAppMentionProcessingWorkflow()
    calls: list[str] = []
    inputs = PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5679", "user": "U_BOB", "text": "and the export filter too"},
        integration_id=1,
        slack_team_id="T_SLACK",
        user_id=42,
        untagged_followup=True,
        untagged_followup_confirmed=True,
    )

    async def fake_execute_activity(activity_fn, *args):
        calls.append(activity_fn.__name__)
        if activity_fn is slack_app_mention_processing.enforce_posthog_code_billing_quota_activity:
            return False
        if activity_fn is slack_app_mention_processing.classify_slack_app_model_override_activity:
            return None
        if activity_fn is slack_app_mention_processing.forward_posthog_code_followup_activity:
            return True
        raise AssertionError(f"unexpected activity: {activity_fn.__name__}")

    with patch.object(
        slack_app_mention_processing, "_execute_posthog_code_activity", side_effect=fake_execute_activity
    ):
        await workflow.run(inputs)

    assert calls == [
        "enforce_posthog_code_billing_quota_activity",
        "classify_slack_app_model_override_activity",
        "forward_posthog_code_followup_activity",
    ]
