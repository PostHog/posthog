import { actions, kea, listeners, path, reducers } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { step3LogicType } from './step3LogicType'

export interface GTMStep {
    title: string
    description: string
    timeline: string
    key_actions: string[]
}

export interface GTMStrategyResponse {
    strategy_description: string
    target_audience: string
    value_proposition: string
    steps: GTMStep[]
}

export const step3Logic = kea<step3LogicType>([
    path(['products', 'founder_mode', 'frontend', 'components', 'step3Logic']),

    actions({
        setProductDescription: (description: string) => ({ description }),
        generateStrategy: true,
        generateStrategySuccess: (result: GTMStrategyResponse) => ({ result }),
        generateStrategyFailure: (error: string) => ({ error }),
    }),

    reducers({
        productDescription: [
            '',
            {
                setProductDescription: (_, { description }) => description,
            },
        ],
        loading: [
            false,
            {
                generateStrategy: () => true,
                generateStrategySuccess: () => false,
                generateStrategyFailure: () => false,
            },
        ],
        result: [
            null as GTMStrategyResponse | null,
            {
                generateStrategySuccess: (_, { result }) => result,
                generateStrategy: () => null,
            },
        ],
        error: [
            null as string | null,
            {
                generateStrategyFailure: (_, { error }) => error,
                generateStrategy: () => null,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        generateStrategy: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                const response = await api.create(`api/projects/${teamId}/founder/go-to-market/`, {
                    product_description: values.productDescription,
                })
                actions.generateStrategySuccess(response as GTMStrategyResponse)
            } catch (e: any) {
                actions.generateStrategyFailure(e.message || 'Failed to generate strategy')
            }
        },
    })),
])
