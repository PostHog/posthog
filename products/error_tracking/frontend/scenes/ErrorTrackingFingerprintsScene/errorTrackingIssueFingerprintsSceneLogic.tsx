import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { ErrorTrackingRelationalIssue } from 'lib/queries/schema'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { errorTrackingIssueFingerprintsQuery } from '../../queries'
import { ErrorTrackingIssueFingerprintsSceneProps } from './ErrorTrackingIssueFingerprintsScene'
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
        loadFingerprintSamples: (issue: ErrorTrackingRelationalIssue, fingerprints: ErrorTrackingFingerprint[]) => ({
            issueId: issue.id,
            firstSeen: issue.first_seen,
            fingerprints: fingerprints ? fingerprints.map((fingerprint) => fingerprint.fingerprint) : null,
        }),
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
        issueFingerprints: {
            loadIssueFingerprints: async () => (await api.errorTracking.fingerprints.list(props.id)).results,
            split: () => values.issueFingerprints.filter((f) => !values.selectedFingerprints.includes(f.fingerprint)),
        },
        fingerprintSamples: [
            [],
            {
                loadFingerprintSamples: async ({ issueId, firstSeen, fingerprints }) => {
                    if (issueId && firstSeen && fingerprints) {
                        const query = errorTrackingIssueFingerprintsQuery(issueId, firstSeen, fingerprints)
                        const response = await api.queryHogQL(query)
                        return response.results.map(([fingerprint, count, samples]) => {
                            return {
                                fingerprint,
                                count,
                                samples,
                            }
                        })
                    }
                    return []
                },
            },
        ],
    })),

    selectors({
        isLoading: [
            (s) => [s.fingerprintSamplesLoading, s.issueLoading, s.issueFingerprintsLoading],
            (fingerprintSamplesLoading, issueLoading, issueFingerprintsLoading) => {
                return fingerprintSamplesLoading || issueLoading || issueFingerprintsLoading
            },
        ],
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
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadIssue()
            actions.loadIssueFingerprints()
        },
    })),
])
