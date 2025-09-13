import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { errorTrackingIssueFingerprintsQuery } from '../../queries'
import {
    ErrorTrackingIssueFingerprint,
    ErrorTrackingIssueFingerprintsSceneProps,
} from './ErrorTrackingIssueFingerprintsScene'
import type { errorTrackingIssueFingerprintsSceneLogicType } from './errorTrackingIssueFingerprintsSceneLogicType'

export const errorTrackingIssueFingerprintsSceneLogic = kea<errorTrackingIssueFingerprintsSceneLogicType>([
    path((key) => [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingFingerprintsScene',
        'errorTrackingIssueFingerprintsSceneLogic',
        key,
    ]),
    props({} as ErrorTrackingIssueFingerprintsSceneProps),
    key(({ id }: ErrorTrackingIssueFingerprintsSceneProps) => id),

    actions({
        loadIssue: true,
        split: (exclusive: boolean) => ({ exclusive }),
        setSelectedFingerprints: (fingerprints: string[]) => ({ fingerprints }),
    }),

    connect({
        actions: [issueActionsLogic, ['splitIssue']],
    }),

    reducers({
        selectedFingerprints: [
            [] as string[],
            {
                setSelectedFingerprints: (_, { fingerprints }) => fingerprints,
            },
        ],
    }),

    loaders(({ values, props }) => ({
        issue: {
            loadIssue: async () => await api.errorTracking.getIssue(props.id),
        },
        fingerprints: [
            [] as ErrorTrackingIssueFingerprint[],
            {
                loadIssueSuccess: async () => {
                    if (values.issue) {
                        const response = await api.queryHogQL(errorTrackingIssueFingerprintsQuery(values.issue))
                        return response.results.map(([fingerprint, count, types, messages]) => ({
                            fingerprint,
                            count,
                            types,
                            messages,
                        }))
                    }
                    return []
                },
                split: () => values.fingerprints.filter((f) => !values.selectedFingerprints.includes(f.fingerprint)),
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.issue],
            (issue): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                ]

                if (issue) {
                    const name = issue.name ?? 'Issue'
                    breadcrumbs.push(
                        {
                            key: [Scene.ErrorTrackingIssue, name],
                            path: urls.errorTrackingIssue(issue.id),
                            name: name,
                        },
                        {
                            key: Scene.ErrorTrackingIssueFingerprints,
                            name: 'Fingerprints',
                        }
                    )
                } else {
                    breadcrumbs.push(
                        {
                            key: [Scene.ErrorTrackingIssue, 'Issue'],
                            name: 'Issue',
                        },
                        {
                            key: Scene.ErrorTrackingIssueFingerprints,
                            name: 'Fingerprints',
                        }
                    )
                }

                return breadcrumbs
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        split: async ({ exclusive }) => {
            await actions.splitIssue(props.id, values.selectedFingerprints, exclusive)
            lemonToast.success('Issue split successfully!')
            actions.setSelectedFingerprints([])
        },
    })),
])
