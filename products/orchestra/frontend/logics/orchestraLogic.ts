import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { orchestraLogicType } from './orchestraLogicType'

export interface OrchestraExecution {
    execution_id: string
    run_id: string
    execution_type: string
    status: string
    started_at: string
    finished_at: string | null
}

export const orchestraLogic = kea<orchestraLogicType>([
    path(['products', 'orchestra', 'frontend', 'logics', 'orchestraLogic']),

    actions({
        setStatusFilter: (status: string | null) => ({ status }),
    }),

    reducers({
        statusFilter: [
            null as string | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
    }),

    loaders(({ values }) => ({
        executions: [
            [] as OrchestraExecution[],
            {
                loadExecutions: async () => {
                    const params: Record<string, string> = {}
                    if (values.statusFilter) {
                        params.status = values.statusFilter
                    }
                    const response = await api.get('api/projects/@current/orchestra/executions/', params)
                    return response.results ?? response
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        setStatusFilter: () => {
            actions.loadExecutions()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExecutions()
    }),
])
