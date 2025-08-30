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
                        return [
                            {
                                assignee: null,
                                description: 'v.getFeatureFlag is not a function',
                                event: 'user signed up',
                                external_issues: [],
                                first_seen: '2025-08-27T13:30:50.188000Z',
                                id: '0198ebb9-60b2-7f80-b61c-5a31d2b4b6f8',
                                last_seen: '2025-08-30T06:29:00.341000-07:00',
                                library: 'web',
                                name: 'UnhandledRejection',
                                odds_ratio: 10.695428571428572,
                                population: {
                                    both: 3,
                                    exception_only: 35,
                                    neither: 12478,
                                    success_only: 100,
                                },
                                status: 'active',
                            },
                            {
                                assignee: null,
                                description:
                                    'AbortError: The play() request was interrupted by a call to pause(). https://goo.gl/LdLk22',
                                event: 'user signed up',
                                external_issues: [],
                                first_seen: '2024-11-22T11:23:39.259160Z',
                                id: 'ce06b0c8-6a3f-4641-b11c-50aedfea17ad',
                                last_seen: '2025-08-30T06:28:34.096000-07:00',
                                library: 'web',
                                name: 'DOMException',
                                odds_ratio: 7.895003162555344,
                                population: {
                                    both: 2,
                                    exception_only: 31,
                                    neither: 12482,
                                    success_only: 102,
                                },
                                status: 'active',
                            },
                        ]
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
