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
        completedInitialLoad: [
            false as boolean,
            {
                loadIssuesSuccess: () => true,
                fakeIssuesSuccess: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        issues: [
            [] as ErrorTrackingCorrelatedIssue[],
            {
                loadIssues: async () => {
                    if (values.event) {
                        const issues = await api.query(errorTrackingIssueCorrelationQuery({ events: [values.event] }), {
                            refresh: 'force_blocking',
                        })
                        return issues.results
                    }
                    return []
                },
                fakeIssues: () => {
                    return [
                        {
                            assignee: null,
                            description: 'No event viewport or meta snapshot found for full snapshot',
                            event: 'recording analyzed',
                            external_issues: [],
                            first_seen: '2025-05-23T11:50:20.614000Z',
                            id: '0196fcfa-e111-71d1-9fcc-c0207b771e62',
                            name: 'Error',
                            odds_ratio: 101.31917369799244,
                            population: {
                                both: 127,
                                exception_only: 16,
                                neither: 43872,
                                success_only: 3437,
                            },
                            status: 'active',
                        },
                        {
                            assignee: null,
                            description:
                                '[KEA] Can not find path "scenes.session-recordings.sessionRecordingDataLogic.0195d95a-21a6-7aac-8b14-db0a68a56c3d" in the store.',
                            event: 'recording analyzed',
                            external_issues: [],
                            first_seen: '2025-03-27T20:50:25.065000Z',
                            id: 'f65965ff-2f68-4463-83bf-06188a940024',
                            name: 'Error',
                            odds_ratio: 49.04945515507125,
                            population: {
                                both: 4,
                                exception_only: 1,
                                neither: 43887,
                                success_only: 3579,
                            },
                            status: 'active',
                        },
                        {
                            assignee: null,
                            description: 'Team ID is not known.',
                            event: 'recording analyzed',
                            external_issues: [],
                            first_seen: '2025-04-28T15:22:50.829000Z',
                            id: '01967cfe-63d6-7701-96ae-21c91ceefb97',
                            name: 'Error',
                            odds_ratio: 48.83115438108484,
                            population: {
                                both: 4,
                                exception_only: 1,
                                neither: 43887,
                                success_only: 3595,
                            },
                            status: 'active',
                        },
                        {
                            assignee: null,
                            description: 'TypeError: Load failed',
                            event: 'recording analyzed',
                            external_issues: [],
                            first_seen: '2025-02-13T11:48:56.139000Z',
                            id: '977db2dd-5461-4937-8602-e27d429c7566',
                            name: 'TypeError',
                            odds_ratio: 48.83115438108484,
                            population: {
                                both: 4,
                                exception_only: 1,
                                neither: 43887,
                                success_only: 3595,
                            },
                            status: 'active',
                        },
                        {
                            assignee: null,
                            description: 'unexpected EOF',
                            event: 'recording analyzed',
                            external_issues: [],
                            first_seen: '2025-05-23T17:47:46.641000Z',
                            id: '0196fe42-5053-7721-b209-b78f68a11e0a',
                            name: 'Error',
                            odds_ratio: 36.65395322939867,
                            population: {
                                both: 3,
                                exception_only: 1,
                                neither: 43887,
                                success_only: 3592,
                            },
                            status: 'active',
                        },
                    ]
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
])
