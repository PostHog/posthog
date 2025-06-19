import { actions, connect, kea, path, reducers } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationType } from '~/types'

import type { messageSendersLogicType } from './messageSendersLogicType'

export const messageSendersLogic = kea<messageSendersLogicType>([
    path(['products', 'messaging', 'frontend', 'messageSendersLogic']),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['deleteIntegration']],
    })),
    actions({
        openNewSenderModal: (integration?: IntegrationType) => ({ integration }),
        closeNewSenderModal: () => null,
    }),
    reducers(() => ({
        isNewSenderModalOpen: [
            false,
            {
                openNewSenderModal: () => true,
                closeNewSenderModal: () => false,
            },
        ],
        selectedIntegration: [
            null as IntegrationType | null,
            {
                openNewSenderModal: (_, { integration }) => integration || null,
                closeNewSenderModal: () => null,
            },
        ],
    })),
])
