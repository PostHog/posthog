import { actions, connect, kea, path, reducers } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationType } from '~/types'

import type { messageChannelsLogicType } from './messageChannelsLogicType'

export type ChannelType = 'email' | 'slack' | 'twilio' | 'webhook'

export const messageChannelsLogic = kea<messageChannelsLogicType>([
    path(['products', 'messaging', 'frontend', 'messageChannelsLogic']),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['deleteIntegration']],
    })),
    actions({
        openNewChannelModal: (integration?: IntegrationType, channelType?: ChannelType) => ({
            integration,
            channelType,
        }),
        closeNewChannelModal: true,
    }),
    reducers(() => ({
        isNewChannelModalOpen: [
            false,
            {
                openNewChannelModal: () => true,
                closeNewChannelModal: () => false,
            },
        ],
        selectedIntegration: [
            null as IntegrationType | null,
            {
                openNewChannelModal: (_, { integration }) => integration || null,
                closeNewChannelModal: () => null,
            },
        ],
        channelType: [
            'email' as ChannelType,
            {
                openNewChannelModal: (_, { channelType }) => channelType || 'email',
                closeNewChannelModal: () => 'email',
            },
        ],
    })),
])
