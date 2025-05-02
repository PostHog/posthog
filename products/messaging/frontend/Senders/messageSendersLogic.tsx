import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { emailSetupModalLogic } from '../EmailSetup/emailSetupModalLogic'
import type { messageSendersLogicType } from './messageSendersLogicType'

export const messageSendersLogic = kea<messageSendersLogicType>([
    path(['products', 'messaging', 'frontend', 'messageSendersLogic']),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['deleteIntegration'], emailSetupModalLogic, ['setIntegration']],
    })),
    actions({
        openNewSenderModal: true,
        closeNewSenderModal: true,
    }),
    reducers(() => ({
        isNewSenderModalOpen: [
            false,
            {
                openNewSenderModal: () => true,
                closeNewSenderModal: () => false,
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingLibrary,
                        name: 'Messaging',
                        path: urls.messagingLibrary(),
                    },
                    {
                        key: 'senders',
                        name: 'Senders',
                        path: urls.messageSenders(),
                    },
                ]
            },
        ],
    }),
])
