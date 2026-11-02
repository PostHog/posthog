import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { SupabaseAuthEmails } from '../SupabaseAuthEmails/SupabaseAuthEmails'
import { ChannelCatalog } from './ChannelCatalog'
import { channelCatalogLogic } from './channelCatalogLogic'
import { ChannelSetupModal } from './ChannelSetupModal'
import { SandboxEmailSenderRow } from './SandboxEmailSenderRow'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const { setupModalOpen, userManagedIntegrations, setupModalType, selectedIntegration, sandboxEmailSender } =
        useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const { sandboxSetupError, sandboxSetupLoading } = useValues(channelCatalogLogic)
    const { retrySandboxSenderSetup } = useActions(channelCatalogLogic)
    const supabaseAuthEmailsEnabled = useFeatureFlag('WORKFLOWS_SUPABASE_AUTH_EMAILS')

    const ownWorkflowIntegrations =
        userManagedIntegrations?.filter((integration) =>
            MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType)
        ) ?? []

    return (
        <>
            <ChannelSetupModal
                isOpen={setupModalOpen}
                channelType={setupModalType}
                integration={selectedIntegration || undefined}
                onClose={closeSetupModal}
                onComplete={() => {
                    markTaskAsCompleted(SetupTaskId.SetUpFirstWorkflowChannel)
                    closeSetupModal()
                }}
            />

            <div className="flex flex-col gap-4" data-attr="message-channels">
                <ChannelCatalog />
                {sandboxSetupError && (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: retrySandboxSenderSetup,
                            loading: sandboxSetupLoading,
                        }}
                    >
                        {sandboxSetupError}
                    </LemonBanner>
                )}
                {sandboxEmailSender && <SandboxEmailSenderRow integration={sandboxEmailSender} />}
                {supabaseAuthEmailsEnabled && <SupabaseAuthEmails />}
                {ownWorkflowIntegrations.length > 0 && (
                    <h3 className="mb-0 text-base font-semibold">Your connections</h3>
                )}
                <EmailIntegrationsList />
                <IntegrationsList titleText="" onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')} />
            </div>
        </>
    )
}
