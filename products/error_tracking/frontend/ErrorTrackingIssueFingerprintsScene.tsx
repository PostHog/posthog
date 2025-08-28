import { actions, connect, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { useEffect } from 'react'

import { LemonCheckbox, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import api from 'lib/api'
import { JSONViewer } from 'lib/components/JSONViewer'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingIssueFingerprintsSceneLogicType } from './ErrorTrackingIssueFingerprintsSceneType'
import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { errorTrackingIssueFingerprintsQuery } from './queries'

export interface ErrorTrackingIssueFingerprintsSceneProps {
    id: string
}

export type ErrorTrackingIssueFingerprint = { fingerprint: string; count: number; types: string[]; messages: string[] }

export const errorTrackingIssueFingerprintsSceneLogic = kea<errorTrackingIssueFingerprintsSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneFingerprintsLogic', key]),
    props({} as ErrorTrackingIssueFingerprintsSceneProps),
    key(({ id }: ErrorTrackingIssueFingerprintsSceneProps) => id),

    actions({
        loadIssue: true,
        setSelectedFingerprints: (fingerprints: string[]) => ({ fingerprints }),
    }),

    connect((props: ErrorTrackingIssueFingerprintsSceneProps) => ({
        values: [errorTrackingIssueSceneLogic(props), ['issue']],
        actions: [issueActionsLogic, ['splitIssue']],
    })),

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
])

export const scene: SceneExport = {
    component: ErrorTrackingIssueFingerprintsScene,
    logic: errorTrackingIssueFingerprintsSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ErrorTrackingIssueFingerprintsScene(): JSX.Element {
    const { selectedFingerprints, fingerprints, fingerprintsLoading } = useValues(
        errorTrackingIssueFingerprintsSceneLogic
    )
    const { loadIssue, setSelectedFingerprints } = useActions(errorTrackingIssueFingerprintsSceneLogic)

    useEffect(() => {
        loadIssue()
    }, [loadIssue])

    const columns = [
        {
            key: 'actions',
            dataIndex: 'fingerprint',
            render: (fingerprint: string) => (
                <LemonCheckbox
                    checked={selectedFingerprints.includes(fingerprint)}
                    onChange={(checked) => {
                        const newSelectedFingerprints = checked
                            ? [...selectedFingerprints, fingerprint]
                            : selectedFingerprints.filter((f) => f !== fingerprint)
                        setSelectedFingerprints(newSelectedFingerprints)
                    }}
                />
            ),
            title: () => (
                <LemonCheckbox
                    checked={fingerprints.length > 0 && selectedFingerprints.length === fingerprints.length}
                    onChange={(checked) => {
                        const newSelectedFingerprints = checked ? fingerprints.map((f) => f.fingerprint) : []
                        setSelectedFingerprints(newSelectedFingerprints)
                    }}
                />
            ),
        },
        {
            title: 'Example type',
            key: 'type',
            dataIndex: 'types',
            render: (types: string[]) =>
                types.length > 0 ? types[0] : <span className="text-muted italic">No exception types</span>,
        },
        {
            title: 'Example message',
            key: 'message',
            dataIndex: 'messages',
            render: (messages: string[]) =>
                messages.length > 0 ? messages[0] : <span className="text-muted italic">No exception messages</span>,
        },
        { title: 'Count', dataIndex: 'count' },
    ] as LemonTableColumns<ErrorTrackingIssueFingerprint>

    return (
        <ErrorTrackingSetupPrompt>
            <p>
                Select the fingerprints that you want to split out from this issue. An individual issue will be created
                for each of the fingerprints.
            </p>
            <LemonTable
                className="w-full"
                loading={fingerprintsLoading}
                dataSource={fingerprints}
                columns={columns}
                expandable={{
                    expandedRowRender: (record) => <JSONViewer src={record} />,
                }}
            />
        </ErrorTrackingSetupPrompt>
    )
}
