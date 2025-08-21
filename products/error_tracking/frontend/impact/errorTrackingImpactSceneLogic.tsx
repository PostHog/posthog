import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { errorTrackingBulkSelectLogic } from '../errorTrackingBulkSelectLogic'
import { errorTrackingIssueCorrelationQuery } from '../queries'
import type { errorTrackingImpactSceneLogicType } from './errorTrackingImpactSceneLogicType'

export const errorTrackingImpactSceneLogic = kea<errorTrackingImpactSceneLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingImpactSceneLogic']),

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

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    path: urls.errorTracking(),
                    name: 'Error tracking',
                },
                {
                    key: Scene.ErrorTrackingImpact,
                    path: urls.errorTrackingImpact(),
                    name: 'Impact',
                },
            ],
        ],
    }),

    subscriptions(({ actions }) => ({
        events: () => actions.setSelectedIssueIds([]),
    })),
])
