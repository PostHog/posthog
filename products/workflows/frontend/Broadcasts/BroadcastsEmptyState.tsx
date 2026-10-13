import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMegaphone } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { onboardingWizardUrl } from '../setupGuide/wizard/onboardingWizardSteps'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

/** The Broadcasts tab before the first broadcast: set up a verified sender first, then write one. */
export function BroadcastsEmptyState(): JSX.Element {
    const { integrations } = useValues(integrationsLogic)
    const { startNewBroadcast } = useActions(newBroadcastAgentLogic)
    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )
    // Until the integrations load, nothing says the sender is missing, so the setup prompt waits.
    const senderReady =
        integrations === null ||
        integrations.some((integration) => integration.kind === 'email' && integration.config?.verified === true)

    // pinned: analytics event name - renaming breaks dashboards
    const capture = (action: 'set-up-email' | 'new-broadcast'): void => {
        posthog.capture('workflows broadcasts empty state clicked', { action })
    }

    return (
        <div
            className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-12 text-center"
            data-attr="broadcasts-empty-state"
        >
            <div className="flex items-center justify-center size-12 rounded-full bg-surface-secondary">
                <IconMegaphone className="size-6" />
            </div>
            <div className="flex flex-col gap-1">
                <h3 className="mb-0 text-base font-semibold">Send your first broadcast</h3>
                <p className="mb-0 max-w-md text-secondary">
                    {senderReady
                        ? 'Send a one-time or scheduled email to a group of people.'
                        : 'Broadcasts send from your own domain. Set up your email sender first, then write the broadcast.'}
                </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
                {!senderReady && (
                    <LemonButton
                        type="primary"
                        to={onboardingWizardUrl('broadcast')}
                        disabledReason={editorDisabledReason}
                        onClick={() => capture('set-up-email')}
                        data-attr="broadcasts-empty-state-set-up-email"
                    >
                        Set up email
                    </LemonButton>
                )}
                <LemonButton
                    type={senderReady ? 'primary' : 'secondary'}
                    disabledReason={editorDisabledReason}
                    onClick={() => {
                        capture('new-broadcast')
                        startNewBroadcast()
                    }}
                    data-attr="broadcasts-empty-new"
                >
                    New broadcast
                </LemonButton>
            </div>
        </div>
    )
}
