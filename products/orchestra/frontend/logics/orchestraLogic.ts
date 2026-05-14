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
    registered_executions: string[]
    started_at: string
    finished_at: string | null
}

const POLL_INTERVAL_MS = 2000

export const orchestraLogic = kea<orchestraLogicType>([
    path(['products', 'orchestra', 'frontend', 'logics', 'orchestraLogic']),

    actions({
        setStatusFilter: (status: string | null) => ({ status }),
        setExecutionDateRange: (date_from: string | null, date_to: string | null) => ({ date_from, date_to }),
        openTriggerModal: true,
        closeTriggerModal: true,
        triggerExecution: (executionType: string, inputJson: string) => ({ executionType, inputJson }),
        refreshAll: true,
    }),

    reducers({
        statusFilter: [
            null as string | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        executionDateRange: [
            { date_from: '-1h' as string | null, date_to: null as string | null },
            {
                setExecutionDateRange: (_, { date_from, date_to }) => ({ date_from, date_to }),
            },
        ],
        triggerModalOpen: [
            false,
            {
                openTriggerModal: () => true,
                closeTriggerModal: () => false,
            },
        ],
        triggerError: [
            null as string | null,
            {
                triggerExecution: () => null,
                openTriggerModal: () => null,
            },
        ],
        executionsLoadedOnce: [
            false,
            {
                loadExecutionsSuccess: () => true,
                loadExecutionsFailure: () => true,
            },
        ],
        deploymentsLoadedOnce: [
            false,
            {
                loadDeploymentsSuccess: () => true,
                loadDeploymentsFailure: () => true,
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
                    const { date_from, date_to } = values.executionDateRange
                    if (date_from) {
                        params.date_from = date_from
                    }
                    if (date_to) {
                        params.date_to = date_to
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
        setExecutionDateRange: () => {
            actions.loadExecutions()
        },
        refreshAll: () => {
            actions.loadActiveDeployment()
            actions.loadDeployments()
            actions.loadExecutions()
        },
        triggerExecution: async ({ executionType, inputJson }) => {
            let parsedInput: unknown = null
            const trimmed = inputJson.trim()
            if (trimmed) {
                try {
                    parsedInput = JSON.parse(trimmed)
                } catch (e: any) {
                    // eslint-disable-next-line no-console
                    console.error('invalid JSON input', e)
                    void values
                    return
                }
            }
            try {
                await api.create('api/projects/@current/orchestra/executions/', {
                    execution_type: executionType,
                    input: parsedInput,
                })
                actions.closeTriggerModal()
                actions.loadExecutions()
            } catch (e: any) {
                // eslint-disable-next-line no-console
                console.error('failed to trigger execution', e)
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
