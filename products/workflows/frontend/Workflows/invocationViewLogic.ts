import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { invocationViewLogicType } from './invocationViewLogicType'

export type InvocationNodeStatus = 'not_reached' | 'succeeded' | 'failed' | 'filtered' | 'waiting' | 'completed'

export type InvocationLogEntry = {
    instanceId: string
    timestamp: Dayjs
    rawTimestamp: string
    level: LogEntryLevel
    message: string
}

export type InvocationViewLogicProps = {
    workflowId: string
    instanceId: string
}

const ACTION_ID_REGEX = /\[Action:([a-zA-Z0-9_-]+)\]/
const PERSON_REGEX = /\[Person:([a-zA-Z0-9_-]+)\|(.*?)\]/
const EVENT_REGEX = /\[Event:([a-zA-Z0-9_-]+)\|(.*?)\|(.*?)\]/

const POLLING_INTERVAL = 5000

export function parseNodeStatuses(logs: InvocationLogEntry[]): {
    nodeStatuses: Record<string, InvocationNodeStatus>
    traversedEdges: string[]
    currentNodeId: string | null
    isCompleted: boolean
    isErrored: boolean
    personInfo: { id: string; name: string } | null
    eventInfo: { uuid: string; name: string; timestamp: string } | null
} {
    const nodeStatuses: Record<string, InvocationNodeStatus> = {}
    const traversedEdges: string[] = []
    let currentNodeId: string | null = null
    let previousNodeId: string | null = null
    let isCompleted = false
    let isErrored = false
    let personInfo: { id: string; name: string } | null = null
    let eventInfo: { uuid: string; name: string; timestamp: string } | null = null

    const sorted = [...logs].sort((a, b) =>
        a.rawTimestamp < b.rawTimestamp ? -1 : a.rawTimestamp > b.rawTimestamp ? 1 : 0
    )

    for (const log of sorted) {
        const msg = log.message

        // Extract person/event info from the starting message
        if (msg.startsWith('Starting') || msg.startsWith('Resuming')) {
            const personMatch = PERSON_REGEX.exec(msg)
            if (personMatch) {
                personInfo = { id: personMatch[1], name: personMatch[2] }
            }
            const eventMatch = EVENT_REGEX.exec(msg)
            if (eventMatch) {
                eventInfo = { uuid: eventMatch[1], name: eventMatch[2], timestamp: eventMatch[3] }
            }

            // Mark trigger as succeeded if starting
            if (msg.startsWith('Starting')) {
                nodeStatuses['trigger'] = 'succeeded'
            }
        }

        // "Executing action [Action:id]"
        if (msg.startsWith('Executing action')) {
            const actionMatch = ACTION_ID_REGEX.exec(msg)
            if (actionMatch) {
                currentNodeId = actionMatch[1]
            }
        }

        // "[Action:id] Function completed in..."
        if (msg.includes('Function completed')) {
            const actionMatch = ACTION_ID_REGEX.exec(msg)
            if (actionMatch) {
                nodeStatuses[actionMatch[1]] = 'succeeded'
            }
        }

        // "[Action:id] Errored: ..."
        if (msg.includes('Errored:')) {
            const actionMatch = ACTION_ID_REGEX.exec(msg)
            if (actionMatch) {
                nodeStatuses[actionMatch[1]] = 'failed'
            }
        }

        // "[Action:id] Skipped due to filter conditions"
        if (msg.includes('Skipped due to filter conditions')) {
            const actionMatch = ACTION_ID_REGEX.exec(msg)
            if (actionMatch) {
                nodeStatuses[actionMatch[1]] = 'filtered'
            }
        }

        // "Workflow moved to action [Action:id]"
        if (msg.startsWith('Workflow moved to action')) {
            const actionMatch = ACTION_ID_REGEX.exec(msg)
            if (actionMatch) {
                const nextId = actionMatch[1]
                previousNodeId = currentNodeId
                currentNodeId = nextId

                if (previousNodeId) {
                    traversedEdges.push(`${previousNodeId}->${nextId}`)
                }
            }
        }

        // "Workflow will pause until ..."
        if (msg.startsWith('Workflow will pause until')) {
            if (currentNodeId) {
                nodeStatuses[currentNodeId] = 'waiting'
            }
        }

        // "Workflow completed"
        if (msg === 'Workflow completed') {
            isCompleted = true
            if (currentNodeId) {
                nodeStatuses[currentNodeId] = 'completed'
            }
        }

        // "Workflow encountered an error: ..."
        if (msg.startsWith('Workflow encountered an error')) {
            isErrored = true
        }

        // "Workflow exited early due to exit condition: ..."
        if (msg.startsWith('Workflow exited early')) {
            isCompleted = true
        }

        // "Workflow is aborting due to ..."
        if (msg.startsWith('Workflow is aborting')) {
            isCompleted = true
        }
    }

    // Also add the edge from trigger to first action if trigger succeeded and there's a next node
    if (nodeStatuses['trigger'] === 'succeeded' && traversedEdges.length > 0) {
        // Find the first "moved to" target after trigger
        const firstEdge = traversedEdges[0]
        if (firstEdge) {
            const firstTarget = firstEdge.split('->')[1]
            if (firstTarget && !traversedEdges.some((e) => e.startsWith('trigger->'))) {
                traversedEdges.unshift(`trigger->${firstTarget}`)
            }
        }
    }

    return { nodeStatuses, traversedEdges, currentNodeId, isCompleted, isErrored, personInfo, eventInfo }
}

export const invocationViewLogic = kea<invocationViewLogicType>([
    path((key) => ['products', 'workflows', 'invocationViewLogic', key]),
    props({} as InvocationViewLogicProps),
    key(({ workflowId, instanceId }) => `${workflowId}:${instanceId}`),
    actions({
        schedulePolling: true,
        stopPolling: true,
    }),
    reducers({
        isPolling: [
            true,
            {
                stopPolling: () => false,
            },
        ],
    }),
    loaders(({ props }) => ({
        logs: [
            [] as InvocationLogEntry[],
            {
                loadLogs: async () => {
                    const query = hogql`
                        SELECT instance_id, timestamp, level, message
                        FROM log_entries
                        WHERE 1=1
                        AND log_source = 'hog_flow'
                        AND log_source_id = ${props.workflowId}
                        AND instance_id = ${props.instanceId}
                        AND timestamp > {filters.dateRange.from}
                        AND timestamp < {filters.dateRange.to}
                        ORDER BY timestamp ASC
                        LIMIT 500`

                    const response = await api.queryHogQL(
                        query,
                        { scene: 'HogFunction', productKey: 'pipeline_destinations' },
                        {
                            refresh: 'force_blocking',
                            filtersOverride: {
                                date_from: '-30d',
                            },
                        }
                    )

                    return response.results.map(
                        (result): InvocationLogEntry => ({
                            instanceId: result[0],
                            timestamp: dayjs(result[1]),
                            rawTimestamp: result[1],
                            level: result[2].toUpperCase(),
                            message: result[3],
                        })
                    )
                },
            },
        ],
    })),
    selectors({
        parsedState: [
            (s) => [s.logs],
            (logs: InvocationLogEntry[]): ReturnType<typeof parseNodeStatuses> => parseNodeStatuses(logs),
        ],
        nodeStatuses: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): Record<string, InvocationNodeStatus> => state.nodeStatuses,
        ],
        traversedEdges: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): string[] => state.traversedEdges,
        ],
        currentNodeId: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): string | null => state.currentNodeId,
        ],
        isCompleted: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): boolean => state.isCompleted,
        ],
        isErrored: [(s) => [s.parsedState], (state: ReturnType<typeof parseNodeStatuses>): boolean => state.isErrored],
        personInfo: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): { id: string; name: string } | null => state.personInfo,
        ],
        eventInfo: [
            (s) => [s.parsedState],
            (state: ReturnType<typeof parseNodeStatuses>): { uuid: string; name: string; timestamp: string } | null =>
                state.eventInfo,
        ],
        isFinished: [
            (s) => [s.isCompleted, s.isErrored],
            (isCompleted: boolean, isErrored: boolean): boolean => isCompleted || isErrored,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadLogsSuccess: () => {
            if (!values.isFinished && values.isPolling) {
                actions.schedulePolling()
            }
        },
        schedulePolling: () => {
            cache.pollingTimeout = setTimeout(() => actions.loadLogs(), POLLING_INTERVAL)
        },
        stopPolling: () => {
            if (cache.pollingTimeout) {
                clearTimeout(cache.pollingTimeout)
                cache.pollingTimeout = null
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLogs()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
