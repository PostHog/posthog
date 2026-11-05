from products.slack_app.backend.logic.onboarding.ai_consent_step import AI_CONSENT_STEP
from products.slack_app.backend.logic.onboarding.github_step import GITHUB_STEP
from products.slack_app.backend.logic.onboarding.inbox_channel_step import INBOX_CHANNEL_STEP
from products.slack_app.backend.logic.onboarding.link_account_step import LINK_ACCOUNT_STEP
from products.slack_app.backend.logic.onboarding.model_step import MODEL_STEP
from products.slack_app.backend.logic.onboarding.replies_step import REPLIES_IN_THREADS_STEP
from products.slack_app.backend.logic.onboarding.sources_step import SOURCES_STEP
from products.slack_app.backend.logic.onboarding.step import OnboardingStepSpec

# In display order. The account link comes first, because the steps after it act for the linked user.
# The workspace steps (AI consent, #posthog-inbox, signals) show only for admins.
ONBOARDING_STEPS: tuple[OnboardingStepSpec, ...] = (
    LINK_ACCOUNT_STEP,
    AI_CONSENT_STEP,
    GITHUB_STEP,
    INBOX_CHANNEL_STEP,
    SOURCES_STEP,
    MODEL_STEP,
    REPLIES_IN_THREADS_STEP,
)
