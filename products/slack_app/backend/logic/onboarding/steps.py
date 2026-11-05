from products.slack_app.backend.logic.onboarding.ai_consent_step import AiConsentStep
from products.slack_app.backend.logic.onboarding.github_step import GithubStep
from products.slack_app.backend.logic.onboarding.inbox_channel_step import InboxChannelStep
from products.slack_app.backend.logic.onboarding.link_account_step import LinkAccountStep
from products.slack_app.backend.logic.onboarding.model_step import ModelStep
from products.slack_app.backend.logic.onboarding.replies_step import RepliesInThreadsStep
from products.slack_app.backend.logic.onboarding.sources_step import SourcesStep
from products.slack_app.backend.logic.onboarding.step import OnboardingStep

# In display order. The account link comes first, because the steps after it act for the linked user.
# The workspace steps (AI consent, #posthog-inbox, signals) show only for admins.
ONBOARDING_STEPS: tuple[OnboardingStep, ...] = (
    LinkAccountStep(),
    AiConsentStep(),
    GithubStep(),
    InboxChannelStep(),
    SourcesStep(),
    ModelStep(),
    RepliesInThreadsStep(),
)
STEPS_BY_KEY: dict[str, OnboardingStep] = {step.key: step for step in ONBOARDING_STEPS}
