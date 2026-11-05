import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { SupabaseAuthEmails } from '../SupabaseAuthEmails/SupabaseAuthEmails'
import { ChannelCatalog } from './ChannelCatalog'
import { channelCatalogLogic } from './channelCatalogLogic'
import { ChannelSetupModal } from './ChannelSetupModal'
import { PUSH_CHANNELS } from './channelSummary'
import { pushTokenImportLogic } from './PushTokenImport/pushTokenImportLogic'
import { PushTokenImportModal } from './PushTokenImport/PushTokenImportModal'
import { SandboxEmailSenderRow } from './SandboxEmailSenderRow'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const {
        setupModalOpen,
        userManagedIntegrations,
        setupModalType,
        selectedIntegration,
        sandboxEmailSender,
        integrationsLoading,
    } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const { sandboxSetupError, sandboxProvisionErrorLoading } = useValues(channelCatalogLogic)
    const { setUpSandboxSender } = useActions(channelCatalogLogic)
    const { openImport } = useActions(pushTokenImportLogic)
    const supabaseAuthEmailsEnabled = useFeatureFlag('WORKFLOWS_SUPABASE_AUTH_EMAILS')
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

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
            <PushTokenImportModal />

            <div className="flex flex-col gap-4" data-attr="message-channels">
                <ChannelCatalog />
                {sandboxSetupError && (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: () => setUpSandboxSender(),
                            loading: sandboxProvisionErrorLoading || integrationsLoading,
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
