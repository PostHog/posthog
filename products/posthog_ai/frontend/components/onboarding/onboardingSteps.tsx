import { IconBolt, IconBook, IconGithub, IconList, IconSparkles } from '@posthog/icons'

// Default, overridable content for the PostHog AI onboarding takeover. Five steps, in order: reset the
// user's prediction of the old assistant, then one step per capability, ending on a real prompt. Pass your
// own array to override.

export type OnboardingStepKey = 'meet' | 'delegate' | 'connect' | 'skills' | 'start'

export interface OnboardingStepMediaSpec {
    /** Served from `frontend/public/`, referenced as a `/static/…` path so the clip stays out of the bundle. */
    src: string
    /** Still shown while the clip loads. It is the frame at `startTime`, so the swap to video is invisible. */
    poster?: string
    /** Seconds into the clip that `poster` was taken from; playback starts and loops here. */
    startTime?: number
}

export interface OnboardingStep {
    key: OnboardingStepKey
    headline: string
    body: string
    /** Stands in for the clip until one is recorded, and gives each step a face of its own either way. */
    icon: JSX.Element
    /**
     * Absent when a step has no clip, in which case the media panel shows `icon` instead. Clips live in
     * `frontend/public/posthog-ai-onboarding/` and are committed as output: what composes them is not in
     * this repo, so they cannot be re-rendered from a clone.
     */
    media?: OnboardingStepMediaSpec
}

export const DEFAULT_ONBOARDING_STEPS: readonly OnboardingStep[] = [
    {
        key: 'meet',
        icon: <IconSparkles />,
        headline: 'PostHog AI is a different agent now',
        body: 'It is a coding agent, and it works across every PostHog product.',
        media: { src: '/static/posthog-ai-onboarding/meet.mp4', poster: '/static/posthog-ai-onboarding/meet.jpg' },
    },
    {
        key: 'delegate',
        icon: <IconList />,
        headline: 'Hand it a hard problem',
        body: 'It writes a plan, you approve it, then it works in the background.',
        media: {
            src: '/static/posthog-ai-onboarding/delegate.mp4',
            poster: '/static/posthog-ai-onboarding/delegate.jpg',
        },
    },
    {
        key: 'skills',
        icon: <IconBook />,
        headline: 'Skills teach it how your team works',
        body: 'Ask it to write the skill, then it follows that every time.',
        media: { src: '/static/posthog-ai-onboarding/skills.mp4', poster: '/static/posthog-ai-onboarding/skills.jpg' },
    },
    // Connect sits directly before the starter prompts: it is the one step with lasting value, and one of
    // those prompts ends in a pull request when GitHub is connected.
    {
        key: 'connect',
        icon: <IconGithub />,
        headline: 'Connect GitHub, so it can see how your product actually works',
        body: 'It reads your code and opens any fix it finds as a pull request.',
        media: {
            src: '/static/posthog-ai-onboarding/connect.mp4',
            poster: '/static/posthog-ai-onboarding/connect.jpg',
        },
    },
    {
        key: 'start',
        icon: <IconBolt />,
        headline: 'Start with something real',
        body: 'The same agent is in Slack and behind the MCP. Pick a question below.',
        media: { src: '/static/posthog-ai-onboarding/start.mp4', poster: '/static/posthog-ai-onboarding/start.jpg' },
    },
]

/** One starter prompt per Job from the onboarding research: decide, fix the bug, build the practice. */
export const DEFAULT_STARTER_PROMPTS: readonly string[] = [
    'What changed in my product this week that I should know about?',
    'Find the biggest issue in my product right now and fix it.',
    'Build me a report on how my product is used and show where each number comes from.',
]

/**
 * Shown instead when the project has no events yet. The default prompts all read the project's data, so on a
 * brand-new org every one of them would dead-end on an empty result.
 */
export const EMPTY_PROJECT_STARTER_PROMPTS: readonly string[] = [
    'Set up PostHog tracking in my codebase.',
    'What events should I track for a product like mine?',
    'Add error tracking and show me the first issues.',
]
