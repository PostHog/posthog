import { actions, connect, defaults, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

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
        unmerge: (fingerprint: string) => ({ fingerprint }),
        loadFingerprintSamples: (issue: ErrorTrackingRelationalIssue, fingerprints: ErrorTrackingFingerprint[]) => ({
            issue,
            fingerprints,
        }),
    }),

    connect(() => ({
        actions: [issueActionsLogic, ['splitIssue', 'splitIssueSuccess', 'mutationFailure']],
    })),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        issueFingerprints: null as ErrorTrackingFingerprint[] | null,
        fingerprintSamples: [] as ErrorTrackingFingerprintSamples[],
        unmergingFingerprints: new Set<string>(),
    }),

    reducers({
        unmergingFingerprints: [
            new Set<string>(),
            {
                unmerge: (state, { fingerprint }) => new Set([...state, fingerprint]),
                splitIssueSuccess: () => new Set<string>(),
                mutationFailure: () => new Set<string>(),
            },
        ],
    }),

    loaders(({ values, props }) => ({
        issue: {
            loadIssue: async () => await api.errorTracking.getIssue(props.id),
        },
        issueFingerprints: {
            loadIssueFingerprints: async () => await api.errorTracking.fingerprints.list(props.id),
            unmerge: ({ fingerprint }: { fingerprint: string }) =>
                (values.issueFingerprints || []).filter((f: ErrorTrackingFingerprint) => f.fingerprint !== fingerprint),
        },
        fingerprintSamples: {
            loadFingerprintSamples: async ({ issue, fingerprints }) => {
                if (issue && fingerprints) {
                    const query = errorTrackingIssueFingerprintsQuery(
                        issue.id,
                        issue.first_seen,
                        fingerprints.map((fingerprint) => fingerprint.fingerprint)
                    )
                    const response = await api.queryHogQL(query, {
                        scene: 'ErrorTrackingIssueFingerprints',
                        productKey: 'error_tracking',
                    })
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
        unmerge: ({ fingerprint }) => {
            const sample = values.fingerprintSamples.find((s) => s.fingerprint === fingerprint)
            const firstSample = sample?.samples?.[0]
            actions.splitIssue(props.id, [
                {
                    fingerprint,
                    ...(firstSample ? { name: firstSample.type, description: firstSample.value } : {}),
                },
            ])
        },
        splitIssueSuccess: ({ newIssueIds }) => {
            if (newIssueIds.length === 0) {
                lemonToast.warning('No fingerprints were unmerged')
                actions.loadIssueFingerprints()
            } else if (newIssueIds.length === 1) {
                lemonToast.success('Fingerprint unmerged successfully', {
                    button: {
                        label: 'View issue',
                        action: () => router.actions.push(urls.errorTrackingIssue(newIssueIds[0])),
                    },
                })
            } else {
                lemonToast.success(`${newIssueIds.length} fingerprints unmerged successfully`)
            }
        },
        mutationFailure: ({ mutationName }) => {
            if (mutationName === 'splitIssues') {
                lemonToast.error('Failed to unmerge fingerprint')
                actions.loadIssueFingerprints()
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadIssue()
            actions.loadIssueFingerprints()
        },
    })),
])
