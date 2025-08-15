import { path, selectors, kea, reducers, actions, listeners, connect } from 'kea'
import { loaders } from 'kea-loaders'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { errorTrackingImpactSceneLogicType } from './errorTrackingImpactSceneLogicType'
import { errorTrackingIssueCorrelationQuery } from '../queries'
import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'
import api from 'lib/api'
import { subscriptions } from 'kea-subscriptions'
import { errorTrackingBulkSelectLogic } from '../errorTrackingBulkSelectLogic'

export const errorTrackingImpactSceneLogic = kea<errorTrackingImpactSceneLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingImpactSceneLogic']),

    connect(() => ({
        actions: [errorTrackingBulkSelectLogic, ['setSelectedIssueIds']],
    })),

    actions({
        setEvent: (event: string | null) => ({ event }),
    }),

    reducers({
        event: [
            null as string | null,
            {
                setEvent: (_, { event }) => event,
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
                    if (values.event) {
                        const issues = await api.query(errorTrackingIssueCorrelationQuery({ event: values.event }), {
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
        setEvent: () => actions.loadIssues(),
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
        event: () => actions.setSelectedIssueIds([]),
    })),
])
