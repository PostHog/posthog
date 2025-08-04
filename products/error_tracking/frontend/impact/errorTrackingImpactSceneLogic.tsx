import { path, selectors, kea, reducers, actions, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { errorTrackingImpactSceneLogicType } from './errorTrackingImpactSceneLogicType'
import api from 'lib/api'
import { errorTrackingIssueCorrelationQuery } from '../queries'
import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'

export const errorTrackingImpactSceneLogic = kea<errorTrackingImpactSceneLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingImpactSceneLogic']),

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
    }),

    loaders(({ values }) => ({
        issues: [
            [] as ErrorTrackingCorrelatedIssue[],
            {
                loadIssues: async () => {
                    if (values.event) {
                        const issues = await api.query(errorTrackingIssueCorrelationQuery({ events: [] }), {
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
                    key: Scene.ErrorTrackingConfiguration,
                    path: urls.errorTrackingImpact(),
                    name: 'Impact',
                },
            ],
        ],
    }),
])
