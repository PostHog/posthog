// Tier 1 — the PostHog AI onboarding takeover: the full-screen "what changed" walkthrough a user sees once
// on their first open of the new PostHog AI, plus the replay affordance that reopens it.
//
// `AiOnboarding` is the lazy wrapper: the dialog pulls quill's dialog chunk and the step media, and the host
// that mounts it (`GlobalModals`) is downloaded on every logged-in page, so the impl is reached only through
// its dynamic `import()`. The logic and the replay button are light and exported eagerly — the button lives
// inside the already-loaded composer, and the logic is what the host reads to decide whether to render.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from deep
// `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { AiOnboarding } from '../components/onboarding/AiOnboarding'
export type { AiOnboardingProps } from '../components/onboarding/AiOnboarding'

export { OnboardingReplayButton } from '../components/onboarding/OnboardingReplayButton'
export type { OnboardingReplayButtonProps } from '../components/onboarding/OnboardingReplayButton'

export { aiOnboardingLogic, POSTHOG_AI_ONBOARDING_SEEN_KEY } from '../logics/aiOnboardingLogic'
export type { AiOnboardingLogicProps } from '../logics/aiOnboardingLogic'

export { DEFAULT_ONBOARDING_STEPS } from '../components/onboarding/onboardingSteps'
export type { OnboardingStep, OnboardingStepKey } from '../components/onboarding/onboardingSteps'
