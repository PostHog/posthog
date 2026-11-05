import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { SupabaseAuthEmails } from '../SupabaseAuthEmails/SupabaseAuthEmails'
import { ChannelCatalog } from './ChannelCatalog'
import { ChannelSetupModal } from './ChannelSetupModal'
import { PUSH_CHANNELS } from './channelSummary'
import { pushTokenImportLogic } from './PushTokenImport/pushTokenImportLogic'
import { PushTokenImportModal } from './PushTokenImport/PushTokenImportModal'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const { setupModalOpen, integrations, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const { openImport } = useActions(pushTokenImportLogic)
    const supabaseAuthEmailsEnabled = useFeatureFlag('WORKFLOWS_SUPABASE_AUTH_EMAILS')
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const allWorkflowIntegrations =
        integrations?.filter((integration) => MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType)) ?? []

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
            <PushTokenImportModal />

            <div className="flex flex-col gap-4" data-attr="message-channels">
                <ChannelCatalog />
                {supabaseAuthEmailsEnabled && <SupabaseAuthEmails />}
                {allWorkflowIntegrations.length > 0 && (
                    <h3 className="mb-0 text-base font-semibold">Your connections</h3>
                )}
                <EmailIntegrationsList />
                <IntegrationsList
                    titleText=""
                    onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')}
                    renderActions={(integration) =>
                        PUSH_CHANNELS.includes(integration.kind as ChannelType) ? (
                            <LemonButton
                                type="secondary"
                                icon={<IconUpload />}
                                onClick={() => openImport(integration)}
                                disabledReason={restrictedReason}
                                data-attr="push-token-import-open"
                            >
                                Import devices
                            </LemonButton>
                        ) : null
                    }
                />
            </div>
        </>
    )
}
