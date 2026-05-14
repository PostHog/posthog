import { actions, afterMount, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { orchestraExecutionLogicType } from './orchestraExecutionLogicType'

export interface OrchestraEvent {
    event_id: number
    event_type: string
    timestamp: string
    attributes: Record<string, unknown>
}

export interface OrchestraExecutionDetail {
    execution_id: string
    run_id: string
    execution_type: string
    status: string
    input: unknown
    result: unknown
    error: unknown
    started_at: string
    finished_at: string | null
    events: OrchestraEvent[]
}

export interface OrchestraExecutionLogicProps {
    executionId: string
}

export const orchestraExecutionLogic = kea<orchestraExecutionLogicType>([
    path(['products', 'orchestra', 'frontend', 'logics', 'orchestraExecutionLogic']),
    props({} as OrchestraExecutionLogicProps),
    key((props) => props.executionId),

    actions({
        retryExecution: true,
    }),

    loaders(({ props }) => ({
        execution: [
            null as OrchestraExecutionDetail | null,
            {
                loadExecution: async () => {
                    return await api.get(
                        `api/projects/@current/orchestra/executions/${props.executionId}/`
                    )
                },
            },
        ],
    })),

    listeners(({ props, actions }) => ({
        retryExecution: async () => {
            try {
                await api.create(
                    `api/projects/@current/orchestra/executions/${props.executionId}/retry/`
                )
                lemonToast.success('Retry queued — reloading…')
                actions.loadExecution()
            } catch (err: any) {
                const detail = err?.data?.detail ?? err?.detail ?? 'Retry failed'
                lemonToast.error(String(detail))
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExecution()
    }),
])
