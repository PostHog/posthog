import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

export const AiVisibilityCreditsExhaustedBanner = (): JSX.Element | null => {
    const { setupContext } = useValues(contentAutopilotSetupLogic)

    if (!setupContext?.ai_credits_exhausted) {
        return null
    }
    return (
        <div data-attr="ai-visibility-credits-exhausted-banner">
            <LemonBanner type="warning" action={{ children: 'Open billing', to: urls.organizationBilling() }}>
                Your organization has used its AI credits, so checks are paused. Add billing or raise your billing limit
                to resume them.
            </LemonBanner>
        </div>
    )
}
