import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
        appendTimelineEvents: (events: OrchestraEvent[], status: string, finishedAt: string | null) => ({
            events,
            status,
            finishedAt,
        }),
    }),

    loaders(({ props }) => ({
        execution: [
            null as OrchestraExecutionDetail | null,
            {
                loadExecution: async () => {
                    return await api.get(`api/projects/@current/orchestra/executions/${props.executionId}/`)
                },
            },
        ],
    })),

    reducers({
        timelineEvents: [
            [] as OrchestraEvent[],
            {
                loadExecutionSuccess: (_, { execution }) => execution?.events ?? [],
                appendTimelineEvents: (_, { events }) => events,
            },
        ],
        timelineStatus: [
            'RUNNING' as string,
            {
                loadExecutionSuccess: (_, { execution }) => execution?.status ?? 'RUNNING',
                appendTimelineEvents: (_, { status }) => status,
            },
        ],
        timelineFinishedAt: [
            null as string | null,
            {
                loadExecutionSuccess: (_, { execution }) => execution?.finished_at ?? null,
                appendTimelineEvents: (_, { finishedAt }) => finishedAt,
            },
        ],
    }),

    selectors({
        isRunning: [(s) => [s.timelineStatus], (status): boolean => status === 'RUNNING'],
    }),

    listeners(({ props, actions, values, cache }) => ({
        retryExecution: async () => {
            try {
                await api.create(`api/projects/@current/orchestra/executions/${props.executionId}/retry/`)
                lemonToast.success('Retry queued — reloading…')
                actions.loadExecution()
            } catch (err: any) {
                const detail = err?.data?.detail ?? err?.detail ?? 'Retry failed'
                lemonToast.error(String(detail))
            }
        },
        loadExecutionSuccess: () => {
            if (values.isRunning && !cache.polling) {
                cache.polling = true
                cache.disposables.add(() => {
                    const id = setInterval(async () => {
                        if (!values.isRunning) {
                            clearInterval(id)
                            cache.polling = false
                            return
                        }
                        try {
                            const data: OrchestraExecutionDetail = await api.get(
                                `api/projects/@current/orchestra/executions/${props.executionId}/`
                            )
                            actions.appendTimelineEvents(data.events, data.status, data.finished_at)
                        } catch {
                            // silently skip failed polls
                        }
                    }, 1000)
                    return () => {
                        clearInterval(id)
                        cache.polling = false
                    }
                }, 'timelinePoll')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExecution()
    }),
])
