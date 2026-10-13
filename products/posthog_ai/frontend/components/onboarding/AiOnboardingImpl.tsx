import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconGithub } from '@posthog/icons'
import { Badge, Button, Text } from '@posthog/quill-primitives'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { type AiOnboardingLogicProps, aiOnboardingLogic } from '../../logics/aiOnboardingLogic'
import { DEFAULT_ONBOARDING_STEPS } from './onboardingSteps'
import { OnboardingTakeover } from './OnboardingTakeover'

const GITHUB_AUTHORIZE_URL = api.integrations.authorizeUrl({ kind: 'github', next: urls.ai() })

function ConnectGithubAction(): JSX.Element {
    const { githubConnected, repositoryCount } = useValues(aiOnboardingLogic)
    const { clickGithubCta } = useActions(aiOnboardingLogic)

    if (githubConnected) {
        return (
            <div className="flex items-center gap-2">
                <Badge variant="success">Connected</Badge>
                <Text size="sm" variant="muted">
                    {repositoryCount === 1
                        ? 'One GitHub organization is connected.'
                        : `${repositoryCount} GitHub organizations are connected.`}
                </Text>
            </div>
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="outline"
                onClick={() => {
                    clickGithubCta()
                    // A full navigation rather than a link: this leaves the app for GitHub's OAuth consent
                    // screen, and an in-app <Link> would be a Lemon component inside a quill surface.
                    window.location.href = GITHUB_AUTHORIZE_URL
                }}
                data-attr="posthog-ai-onboarding-connect-github"
            >
                <IconGithub />
                Connect GitHub
            </Button>
        </div>
    )
}

function StarterPromptsAction(): JSX.Element {
    const { starterPrompts } = useValues(aiOnboardingLogic)
    const { selectStarterPrompt } = useActions(aiOnboardingLogic)

    return (
        <div className="flex flex-col gap-2">
            {starterPrompts.map((prompt) => (
                <Button
                    key={prompt}
                    variant="outline"
                    // Buttons are nowrap by default, which on a narrow viewport widens the whole column to
                    // the longest prompt and scrolls the dialog sideways.
                    className="h-auto justify-start whitespace-normal py-1.5 text-start"
                    onClick={() => selectStarterPrompt(prompt)}
                    data-attr="posthog-ai-onboarding-starter-prompt"
                >
                    {prompt}
                </Button>
            ))}
        </div>
    )
}

export interface AiOnboardingProps extends AiOnboardingLogicProps {
    /**
     * Whether the host surface is showing PostHog AI to a user who hasn't seen the takeover. The host owns
     * this because the answer depends on the runtime and the entry point, neither of which this surface
     * knows about.
     */
    autoOpen: boolean
}

/**
 * The onboarding takeover wired to its logic. Opens itself once when the host says the user is eligible,
 * and afterwards only via the replay button.
 */
export function AiOnboarding({ panelId, autoOpen }: AiOnboardingProps): JSX.Element | null {
    const logicProps: AiOnboardingLogicProps = useMemo(() => ({ panelId }), [panelId])
    const { isOpen, stepIndex, hasSeenOnboarding, user } = useValues(aiOnboardingLogic(logicProps))
    const { openOnboarding, closeOnboarding, finishOnboarding, setStepIndex, replayMedia } = useActions(
        aiOnboardingLogic(logicProps)
    )

    useEffect(() => {
        // `user` gates the whole thing: the seen flag lives on it, so acting before it resolves would show
        // the takeover again to someone who already dismissed it.
        if (autoOpen && user && !hasSeenOnboarding && !isOpen) {
            openOnboarding()
        }
        // Only the eligibility edge should open it. `isOpen` is deliberately excluded: including it would
        // re-open the takeover the moment the user dismisses it, since the seen flag round-trips the server.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [autoOpen, user, hasSeenOnboarding, openOnboarding])

    if (!isOpen) {
        return null
    }

    return (
        <BindLogic logic={aiOnboardingLogic} props={logicProps}>
            <OnboardingTakeover
                open={isOpen}
                steps={DEFAULT_ONBOARDING_STEPS}
                stepIndex={stepIndex}
                onStepIndexChange={setStepIndex}
                onDismiss={closeOnboarding}
                onFinish={finishOnboarding}
                onReplayMedia={replayMedia}
                stepActions={{
                    connect: <ConnectGithubAction />,
                    start: <StarterPromptsAction />,
                }}
            />
        </BindLogic>
    )
}
