import { actions, kea, listeners, path, reducers } from 'kea'

import type { fixWithAiLogicType } from './fixWithAiLogicType'

export type FixWithAIStatus = 'not_started' | 'in_progress' | 'done'

export const fixWithAiLogic = kea<fixWithAiLogicType>([
    path(['products', 'error_tracking', 'frontend', 'components', 'IssueAIFix', 'fixWithAiLogic']),

    actions({
        setIntegrationId: (integrationId: number) => ({ integrationId }),
        setRepository: (repository: string) => ({ repository }),
        generateFix: true,
        setFixStatus: (fixStatus: FixWithAIStatus) => ({ fixStatus }),
        setRepositoryPopoverVisible: (repositoryPopoverVisible: boolean) => ({ repositoryPopoverVisible }),
    }),

    reducers({
        integrationId: [
            null as number | null,
            {
                setIntegrationId: (_, { integrationId }) => integrationId,
            },
        ],
        repository: [
            null as string | null,
            {
                setRepository: (_, { repository }) => repository,
            },
        ],
        fixStatus: [
            'not_started',
            {
                setFixStatus: (_, { fixStatus }) => fixStatus,
            },
        ],
        repositoryPopoverVisible: [
            false,
            {
                setRepositoryPopoverVisible: (_, { repositoryPopoverVisible }) => repositoryPopoverVisible,
            },
        ],
    }),

    listeners(({ actions }) => ({
        generateFix: async () => {
            actions.setFixStatus('in_progress')

            await new Promise((resolve) => setTimeout(resolve, 3000))

            actions.setFixStatus('done')
        },
    })),
])
