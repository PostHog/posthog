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

export interface OrchestraDeployment {
    id: number
    code_version: string
    image_name: string
    container_id: string
    task_queue: string
    status: string
    started_at: string
    finished_at: string | null
}

const POLL_INTERVAL_MS = 10000

export const orchestraLogic = kea<orchestraLogicType>([
    path(['products', 'orchestra', 'frontend', 'logics', 'orchestraLogic']),

    actions({
        setStatusFilter: (status: string | null) => ({ status }),
        triggerGreeting: true,
        refreshAll: true,
    }),

    reducers({
        statusFilter: [
            null as string | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        triggerError: [
            null as string | null,
            {
                triggerGreeting: () => null,
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
        deployments: [
            [] as OrchestraDeployment[],
            {
                loadDeployments: async () => {
                    const response = await api.get('api/projects/@current/orchestra/deployments/')
                    return response.results ?? response
                },
            },
        ],
        activeDeployment: [
            null as OrchestraDeployment | null,
            {
                loadActiveDeployment: async () => {
                    try {
                        return await api.get('api/projects/@current/orchestra/deployments/active/')
                    } catch {
                        return null
                    }
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setStatusFilter: () => {
            actions.loadExecutions()
        },
        refreshAll: () => {
            actions.loadDeployments()
            actions.loadActiveDeployment()
        },
        triggerGreeting: async () => {
            try {
                await api.create('api/projects/@current/orchestra/executions/', {
                    execution_type: 'greeting_execution',
                    input: { name: 'World', age: 30 },
                })
                actions.loadExecutions()
            } catch (e: any) {
                // eslint-disable-next-line no-console
                console.error('failed to trigger greeting', e)
                // The reducer below would store this, but we keep it minimal for the demo.
                void values
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.refreshAll()
        cache.disposables.add(() => {
            const id = setInterval(() => actions.refreshAll(), POLL_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'orchestraPoll')
    }),
])
