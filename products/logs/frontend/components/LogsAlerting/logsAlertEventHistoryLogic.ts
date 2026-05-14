import { actions, afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { logsAlertsEventsList } from 'products/logs/frontend/generated/api'
import { LogsAlertEventApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertEventHistoryLogicType } from './logsAlertEventHistoryLogicType'

export interface LogsAlertEventHistoryLogicProps {
    alertId: string
}

export interface EventsPage {
    results: LogsAlertEventApi[]
    next: string | null
    count: number
}

export const logsAlertEventHistoryLogic = kea<logsAlertEventHistoryLogicType>([
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsAlerting', 'logsAlertEventHistoryLogic', key]),
    props({} as LogsAlertEventHistoryLogicProps),
    key((props) => props.alertId),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadMore: true,
    }),

    loaders(({ props, values }) => ({
        eventsPage: [
            { results: [], next: null, count: 0 } as EventsPage,
            {
                loadEvents: async () => {
                    const projectId = String(values.currentTeamId)
                    const response = await logsAlertsEventsList(projectId, props.alertId)
                    return {
                        results: response.results ?? [],
                        next: response.next ?? null,
                        count: response.count ?? 0,
                    }
                },
                loadMore: async () => {
                    const nextUrl = values.eventsPage.next
                    if (!nextUrl) {
                        return values.eventsPage
                    }
                    const res = await fetch(nextUrl, { credentials: 'include' })
                    if (!res.ok) {
                        throw new Error(`Failed to load more events: ${res.status} ${res.statusText}`)
                    }
                    const data = (await res.json()) as {
                        results?: LogsAlertEventApi[]
                        next?: string | null
                        count?: number
                    }
                    return {
                        results: [...values.eventsPage.results, ...(data.results ?? [])],
                        next: data.next ?? null,
                        count: data.count ?? values.eventsPage.count,
                    }
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadEvents()
    }),
])
