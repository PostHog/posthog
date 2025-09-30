import { actions, connect, defaults, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { errorTrackingIssueFingerprintsQuery } from '../../queries'
import {
    ErrorTrackingFingerprintSamples,
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
        loadFingerprintSamples: (issue: ErrorTrackingRelationalIssue, fingerprints: ErrorTrackingFingerprint[]) => ({
            issue,
            fingerprints,
        }),
    }),

    connect(() => ({
        actions: [issueActionsLogic, ['splitIssue']],
    })),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        issueFingerprints: null as ErrorTrackingFingerprint[] | null,
        fingerprintSamples: [] as ErrorTrackingFingerprintSamples[],
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
            split: () =>
                (values.issueFingerprints || []).filter(
                    (f: ErrorTrackingFingerprint) => !values.selectedFingerprints.includes(f.fingerprint)
                ),
        },
        fingerprintSamples: {
            loadFingerprintSamples: async ({ issue, fingerprints }) => {
                if (issue && fingerprints) {
                    const query = errorTrackingIssueFingerprintsQuery(
                        issue.id,
                        issue.first_seen,
                        fingerprints.map((fingerprint) => fingerprint.fingerprint)
                    )
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
                        iconType: 'error_tracking',
                    },
                ]

                if (issue) {
                    const name = issue.name ?? 'Issue'
                    breadcrumbs.push(
                        {
                            key: [Scene.ErrorTrackingIssue, name],
                            path: urls.errorTrackingIssue(issue.id),
                            name: name,
                            iconType: 'error_tracking',
                        },
                        {
                            key: Scene.ErrorTrackingIssueFingerprints,
                            name: 'Fingerprints',
                            iconType: 'error_tracking',
                        }
                    )
                } else {
                    breadcrumbs.push(
                        {
                            key: [Scene.ErrorTrackingIssue, 'Issue'],
                            name: 'Issue',
                            iconType: 'error_tracking',
                        },
                        {
                            key: Scene.ErrorTrackingIssueFingerprints,
                            name: 'Fingerprints',
                            iconType: 'error_tracking',
                        }
                    )
                }

                return breadcrumbs
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        split: ({ exclusive }) => {
            actions.splitIssue(props.id, values.selectedFingerprints, exclusive)
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
