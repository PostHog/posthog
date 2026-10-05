import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { SetupTaskId } from 'lib/components/ProductSetup'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { isSandboxEmailSender } from 'lib/integrations/utils'

import { ChannelSetupModal } from './ChannelSetupModal'
import { SandboxEmailSenderRow } from './SandboxEmailSenderRow'

const HedgehogReporter = pngHoggie(reporterPng)

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const {
        setupModalOpen,
        integrations,
        integrationsLoading,
        setupModalType,
        selectedIntegration,
        sandboxEmailSender,
    } = useValues(integrationsLogic)
    const { openSetupModal, closeSetupModal, markTaskAsCompleted, ensureSandboxEmailSender } =
        useActions(integrationsLogic)

    useEffect(() => {
        ensureSandboxEmailSender()
    }, [ensureSandboxEmailSender])

    const ownWorkflowIntegrations =
        integrations?.filter(
            (integration) =>
                MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType) && !isSandboxEmailSender(integration)
        ) ?? []

    const showProductIntroduction = !integrationsLoading && !ownWorkflowIntegrations.length

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
                {integrationsLoading && !integrations?.length && (
                    <>
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                    </>
                )}
                {showProductIntroduction && (
                    <ProductIntroduction
                        thingName="channel integration"
                        description="Set up messaging channels to automatically send emails, SMS, or Slack notifications triggered by user actions and events."
                        docsURL="https://posthog.com/docs/workflows/configure-channels"
                        action={() => openSetupModal(undefined, 'email')}
                        customHog={HedgehogReporter}
                        isEmpty
                    />
                )}
                {sandboxEmailSender && <SandboxEmailSenderRow integration={sandboxEmailSender} />}
                <EmailIntegrationsList />
                <IntegrationsList titleText="" onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')} />
            </div>
        </>
    )
}
