import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { dayjs } from 'lib/dayjs'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { EventType, PropertyFilterType } from '~/types'

import type { MCPDetailDrawerPosition } from '../components/MCPDetailDrawer'

export interface ActivityDrawerRow {
    eventId: string
    sessionId: string | null
    timestamp: string
    /** Absent when opened from a link. */
    event?: EventType
}

export type ActivityDrawerOpenSource = 'list' | 'step' | 'url'

// pinned: URL search params — renaming them breaks shared drawer links
const SESSION_PARAM = 'session'
const CALL_PARAM = 'call'
const TIMESTAMP_PARAM = 'ts'
const DRAWER_PARAMS = [SESSION_PARAM, CALL_PARAM, TIMESTAMP_PARAM]

// The event page looks an event up in the same window around its timestamp.
const EVENT_LOOKUP_MARGIN_SECONDS = 15

export function toActivityDrawerRow(result: unknown): ActivityDrawerRow | null {
    const event = Array.isArray(result) ? result[0] : null
    if (!event?.uuid || !event.timestamp) {
        return null
    }
    const sessionId = event.properties?.$session_id
    return {
        eventId: String(event.uuid),
        sessionId: sessionId ? String(sessionId) : null,
        timestamp: String(event.timestamp),
        event,
    }
}

export async function fetchToolCallEvent(eventId: string, timestamp: string): Promise<EventType | null> {
    const at = dayjs(timestamp)
    const query: EventsQuery = {
        kind: NodeKind.EventsQuery,
        select: ['*'],
        event: MCP_TOOL_CALL_EVENT,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                key: `uuid = '${eventId.replaceAll(/[^a-f0-9-]/g, '')}'`,
                value: null,
            },
        ],
        after: at.subtract(EVENT_LOOKUP_MARGIN_SECONDS, 'second').toISOString(),
        before: at.add(EVENT_LOOKUP_MARGIN_SECONDS, 'second').toISOString(),
        limit: 1,
    }
    const response = await api.query(query)
    return (response.results?.[0]?.[0] as EventType | undefined) ?? null
}

export function withoutActivityDrawerParams<T>(params: Record<string, T>): Record<string, T> {
    return Object.fromEntries(Object.entries(params).filter(([name]) => !DRAWER_PARAMS.includes(name)))
}

export const activityDrawerLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'activityDrawerLogic']),
    actions({
        setRows: (rows: ActivityDrawerRow[]) => ({ rows }),
        openRow: (row: ActivityDrawerRow, source: ActivityDrawerOpenSource) => ({ row, source }),
        stepTo: (direction: 'previous' | 'next') => ({ direction }),
        close: true,
    }),
    reducers({
        rows: [[] as ActivityDrawerRow[], { setRows: (_, { rows }) => rows }],
        openedRow: [
            null as ActivityDrawerRow | null,
            {
                openRow: (_, { row }) => row,
                close: () => null,
            },
        ],
    }),
    loaders(() => ({
        loadedEvent: [
            null as EventType | null,
            {
                loadEvent: async (row: ActivityDrawerRow, breakpoint) => {
                    const event = await fetchToolCallEvent(row.eventId, row.timestamp)
                    breakpoint()
                    return event
                },
            },
        ],
    })),
    reducers({
        eventFailed: [
            false,
            {
                loadEvent: () => false,
                loadEventFailure: () => true,
            },
        ],
    }),
    selectors({
        position: [
            (s) => [s.rows, s.openedRow],
            (rows: ActivityDrawerRow[], openedRow: ActivityDrawerRow | null): MCPDetailDrawerPosition | null => {
                const index = openedRow ? rows.findIndex((row) => row.eventId === openedRow.eventId) : -1
                return index >= 0 ? { index, total: rows.length } : null
            },
        ],
        previousRow: [
            (s) => [s.rows, s.position],
            (rows: ActivityDrawerRow[], position: MCPDetailDrawerPosition | null): ActivityDrawerRow | null =>
                position && position.index > 0 ? rows[position.index - 1] : null,
        ],
        nextRow: [
            (s) => [s.rows, s.position],
            (rows: ActivityDrawerRow[], position: MCPDetailDrawerPosition | null): ActivityDrawerRow | null =>
                position && position.index < rows.length - 1 ? rows[position.index + 1] : null,
        ],
        event: [
            (s) => [s.openedRow, s.loadedEvent],
            (openedRow: ActivityDrawerRow | null, loadedEvent: EventType | null): EventType | null =>
                openedRow?.event ?? (loadedEvent?.uuid === openedRow?.eventId ? loadedEvent : null),
        ],
        fullPageHref: [
            (s) => [s.openedRow],
            (openedRow: ActivityDrawerRow | null): string | null =>
                openedRow ? urls.event(openedRow.eventId, openedRow.timestamp, MCP_TOOL_CALL_EVENT) : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        openRow: ({ row, source }) => {
            if (source === 'list') {
                posthog.capture('mcp analytics drawer opened', { list: 'activity' })
            }
            if (!row.event && row.eventId !== values.loadedEvent?.uuid) {
                actions.loadEvent(row)
            }
        },
        stepTo: ({ direction }) => {
            const row = direction === 'previous' ? values.previousRow : values.nextRow
            if (row) {
                actions.openRow(row, 'step')
            }
        },
    })),
    actionToUrl(() => {
        const withParams = (
            params: Record<string, string>
        ): [string, Record<string, any>, Record<string, any>] | undefined => {
            const { currentLocation } = router.values
            return [
                currentLocation.pathname,
                { ...withoutActivityDrawerParams(currentLocation.searchParams), ...params },
                currentLocation.hashParams,
            ]
        }
        return {
            openRow: ({ row }) =>
                withParams({
                    ...(row.sessionId ? { [SESSION_PARAM]: row.sessionId } : {}),
                    [CALL_PARAM]: row.eventId,
                    [TIMESTAMP_PARAM]: row.timestamp,
                }),
            close: () => withParams({}),
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsActivity()]: (_, searchParams) => {
            const sessionId = searchParams[SESSION_PARAM]
            const eventId = searchParams[CALL_PARAM]
            const timestamp = searchParams[TIMESTAMP_PARAM]
            if (typeof eventId === 'string' && typeof timestamp === 'string') {
                if (eventId !== values.openedRow?.eventId) {
                    // A row from the loaded feed carries its event, so a link to a loaded call skips the lookup.
                    const loadedRow = values.rows.find((row) => row.eventId === eventId)
                    actions.openRow(
                        loadedRow ?? {
                            eventId,
                            sessionId: typeof sessionId === 'string' ? sessionId : null,
                            timestamp,
                        },
                        'url'
                    )
                }
            } else if (values.openedRow) {
                actions.close()
            }
        },
    })),
])
