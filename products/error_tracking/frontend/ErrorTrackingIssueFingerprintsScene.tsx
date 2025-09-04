import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCheckbox, LemonSelect, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { errorTrackingIssueFingerprintsSceneLogic } from './errorTrackingIssueFingerprintsSceneLogic'

export type ErrorTrackingIssueFingerprint = { fingerprint: string; count: number; types: string[]; messages: string[] }

export interface ErrorTrackingIssueFingerprintsSceneProps {
    id: string
}

export const scene: SceneExport<ErrorTrackingIssueFingerprintsSceneProps> = {
    component: ErrorTrackingIssueFingerprintsScene,
    logic: errorTrackingIssueFingerprintsSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ErrorTrackingIssueFingerprintsScene(): JSX.Element {
    const { selectedFingerprints, fingerprints, fingerprintsLoading } = useValues(
        errorTrackingIssueFingerprintsSceneLogic
    )
    const { loadIssue, setSelectedFingerprints, split } = useActions(errorTrackingIssueFingerprintsSceneLogic)

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
                    disabledReason={
                        fingerprints.length === 1
                            ? 'You cannot split an issue that only has one fingerprint'
                            : undefined
                    }
                />
            ),
            title: (
                <LemonCheckbox
                    checked={fingerprints.length > 0 && selectedFingerprints.length === fingerprints.length}
                    disabledReason={
                        fingerprints.length === 1
                            ? 'You cannot split an issue that only has one fingerprint'
                            : undefined
                    }
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

    const disabledReason =
        selectedFingerprints.length === fingerprints.length
            ? 'You must leave at least one fingerprint associated with the issue'
            : selectedFingerprints.length === 0
              ? 'Select at least one fingerprint'
              : fingerprints.length === 1
                ? 'You cannot split an issue that only has one fingerprint'
                : undefined

    return (
        <ErrorTrackingSetupPrompt>
            <div className="space-y-2">
                <div>
                    Select the fingerprints that you want to split out from this issue. An individual issue will be
                    created for each of the fingerprints.
                </div>

                {selectedFingerprints.length <= 1 ? (
                    <LemonButton
                        size="small"
                        type="primary"
                        disabledReason={disabledReason}
                        onClick={() => split(true)}
                    >
                        Split
                    </LemonButton>
                ) : (
                    <LemonSelect
                        size="small"
                        type="primary"
                        placeholder="Split"
                        options={[
                            { value: false, label: 'Split fingerprints into a single issue' },
                            { value: true, label: 'Split fingerprints into individual issues' },
                        ]}
                        onSelect={(value) => split(value)}
                        disabledReason={disabledReason}
                    />
                )}

                <LemonTable
                    className="w-full"
                    loading={fingerprintsLoading}
                    dataSource={fingerprints}
                    columns={columns}
                    expandable={{
                        expandedRowRender: (record) => <JSONViewer src={record} />,
                    }}
                />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}
