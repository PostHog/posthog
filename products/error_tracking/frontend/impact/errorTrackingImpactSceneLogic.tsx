import { path, selectors, kea } from 'kea'
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

    loaders({
        issues: [
            [] as ErrorTrackingCorrelatedIssue[],
            {
                loadIssues: async () => {
                    const issues = await api.query(errorTrackingIssueCorrelationQuery({ events: [] }), {
                        refresh: 'force_blocking',
                    })
                    return issues.results
                },
            },
        ],
    }),

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
