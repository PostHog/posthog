import { useActions, useValues } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-sync/WizardCommandBlock'

import { firstRunAgentHelpLogic, MissingData } from './firstRunAgentHelpLogic'

const SIGNUP_EVENT_PROMPT = `My app uses PostHog. Send an event to PostHog each time someone signs up, so a PostHog workflow can email new users.

1. Find the code that runs once a signup has succeeded. Prefer server-side code if the app has a backend.
2. If PostHog is not set up in that part of the app yet, install and initialize the PostHog SDK the way the PostHog docs describe for this framework.
3. Capture an event named exactly "user signed up" for the new user. Use the user's ID as the distinct ID.
4. Set the user's email address as the "email" person property. A server SDK takes it in the person properties ($set) of that capture call. In posthog-js, call posthog.identify(userId, { email }).

Follow the conventions of this codebase and keep the change small.`

const EMAIL_PROMPT = `My app uses PostHog. Make sure PostHog knows the email address of each user, so a PostHog workflow can email them.

1. Find where the app identifies users with PostHog. This usually happens after login and after signup.
2. If the app never identifies users, identify them when they log in and when they sign up. Use the user's ID as the distinct ID.
3. Set the user's email address as the "email" person property. In posthog-js, call posthog.identify(userId, { email }). A server SDK takes it in the person properties ($set) of an identify or capture call.

Follow the conventions of this codebase and keep the change small.`

interface AgentHelp {
    type: 'info' | 'warning'
    message: string
    prompt: string
    wizardCheck: string
}

const AGENT_HELP: Record<MissingData, AgentHelp> = {
    signup_event: {
        type: 'info',
        message:
            'You can test an email right now. To send it to real signups, your app needs to tell PostHog when someone signs up.',
        prompt: SIGNUP_EVENT_PROMPT,
        wizardCheck: 'Check that its changes send a "user signed up" event when someone signs up.',
    },
    email: {
        type: 'warning',
        message:
            "People in this project have no email address yet, so they would miss your emails. Your app needs to send each user's email to PostHog.",
        prompt: EMAIL_PROMPT,
        wizardCheck: "Check that its changes set each user's email when your app identifies them.",
    },
}

export function FirstRunAgentHelp(): JSX.Element | null {
    const { missingData, wizardShown } = useValues(firstRunAgentHelpLogic)
    const { reportPromptCopied, setWizardShown } = useActions(firstRunAgentHelpLogic)
    const { isCloudOrDev } = useWizardCommand()

    if (!missingData) {
        return null
    }
    const { type, message, prompt, wizardCheck } = AGENT_HELP[missingData]

    return (
        <LemonBanner type={type} alignItems="start">
            <div className="flex flex-col gap-2" data-attr={`workflows-first-run-agent-help-${missingData}`}>
                <span>{message}</span>
                <div className="flex flex-wrap items-center gap-2">
                    <AgentPromptButton
                        actions={[
                            { key: missingData, label: 'prompt for your coding agent', buildPrompt: () => prompt },
                        ]}
                        agentKeys={['clipboard']}
                        storageKey="workflows-first-run-agent-help"
                        variant="outline"
                        onRun={() => reportPromptCopied()}
                        data-attr="workflows-first-run-copy-agent-prompt"
                    />
                    {isCloudOrDev && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconMagicWand />}
                            active={wizardShown}
                            aria-expanded={wizardShown}
                            onClick={() => setWizardShown(!wizardShown)}
                            data-attr="workflows-first-run-show-wizard"
                        >
                            Let the Wizard do it
                        </LemonButton>
                    )}
                </div>
                {wizardShown && (
                    <WizardCommandBlock
                        hideHog
                        description={`Run this in the folder of your app. The setup agent sets up PostHog in your code. ${wizardCheck}`}
                    />
                )}
            </div>
        </LemonBanner>
    )
}
