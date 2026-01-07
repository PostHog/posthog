import { kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'

import type { logExploreAILogicType } from './logExploreAILogicType'
import { LogExplanation } from './types'

export interface LogExploreAILogicProps {
    logUuid: string
    logTimestamp: string
}

export const logExploreAILogic = kea<logExploreAILogicType>([
    props({} as LogExploreAILogicProps),
    key((props) => props.logUuid),
    path((key) => [
        'products',
        'logs',
        'frontend',
        'components',
        'LogsViewer',
        'LogDetailsModal',
        'logExploreAILogic',
        key,
    ]),

    selectors({
        dataProcessingAccepted: [
            () => [organizationLogic.selectors.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
    }),

    reducers({
        explanationError: [
            null as string | null,
            {
                loadExplanation: () => null,
                loadExplanationFailure: (_, { error }) => error || 'Failed to generate explanation',
            },
        ],
    }),

    loaders(({ props, values }) => ({
        explanation: {
            __default: null as LogExplanation | null,
            loadExplanation: async (): Promise<LogExplanation> => {
                if (!values.dataProcessingAccepted) {
                    throw new Error('AI data processing must be approved before generating explanations')
                }
                return await api.logs.explain(props.logUuid, props.logTimestamp)
            },
        },
    })),
])
