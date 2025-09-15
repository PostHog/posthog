import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'

import { errorTrackingBulkSelectLogic } from 'products/error_tracking/frontend/errorTrackingBulkSelectLogic'
import { errorTrackingIssueCorrelationQuery } from 'products/error_tracking/frontend/queries'

import type { errorTrackingImpactListLogicType } from './errorTrackingImpactListLogicType'

export const errorTrackingImpactListLogic = kea<errorTrackingImpactListLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingImpactListLogic']),

    connect(() => ({
        actions: [errorTrackingBulkSelectLogic, ['setSelectedIssueIds']],
    })),

    actions({
        setEvents: (events: string[]) => ({ events }),
    }),

    reducers({
        events: [
            null as string[] | null,
            {
                setEvents: (_, { events }) => events,
            },
        ],
        completedInitialLoad: [
            false as boolean,
            {
                loadIssuesSuccess: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        issues: [
            [] as ErrorTrackingCorrelatedIssue[],
            {
                loadIssues: async () => {
                    if (values.events) {
                        const issues = await api.query(errorTrackingIssueCorrelationQuery({ events: values.events }), {
                            refresh: 'force_blocking',
                        })
                        return issues.results
                    }
                    return []
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        setEvents: () => actions.loadIssues(),
    })),

    subscriptions(({ actions }) => ({
        events: () => actions.setSelectedIssueIds([]),
    })),
])
