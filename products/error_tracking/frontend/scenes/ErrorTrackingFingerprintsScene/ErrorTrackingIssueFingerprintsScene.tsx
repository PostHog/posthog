import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCheckbox, LemonSelect, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { errorTrackingIssueFingerprintsSceneLogic } from './errorTrackingIssueFingerprintsSceneLogic'

export type ErrorTrackingFingerprintSamples = {
    fingerprint: string
    count: number
    samples: { type: string; value: string }[]
}

export interface ErrorTrackingIssueFingerprintsSceneProps {
    id: string
}

export const scene: SceneExport<ErrorTrackingIssueFingerprintsSceneProps> = {
    component: ErrorTrackingIssueFingerprintsScene,
    logic: errorTrackingIssueFingerprintsSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ErrorTrackingIssueFingerprintsScene(): JSX.Element {
    const { issue, issueFingerprints, selectedFingerprints, fingerprintSamples, isLoading } = useValues(
        errorTrackingIssueFingerprintsSceneLogic
    )
    const { loadFingerprintSamples, setSelectedFingerprints, split } = useActions(
        errorTrackingIssueFingerprintsSceneLogic
    )

    useEffect(() => {
        if (issue && issueFingerprints) {
            loadFingerprintSamples(issue, issueFingerprints)
        }
    }, [issue, issueFingerprints, loadFingerprintSamples])

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
                        fingerprintSamples.length === 1
                            ? 'You cannot split an issue that only has one fingerprint'
                            : undefined
                    }
                />
            ),
            width: '30px',
            title: (
                <LemonCheckbox
                    checked={fingerprintSamples.length > 0 && selectedFingerprints.length === fingerprintSamples.length}
                    disabledReason={
                        fingerprintSamples.length === 1
                            ? 'You cannot split an issue that only has one fingerprint'
                            : undefined
                    }
                    onChange={(checked) => {
                        const newSelectedFingerprints = checked ? fingerprintSamples.map((f) => f.fingerprint) : []
                        setSelectedFingerprints(newSelectedFingerprints)
                    }}
                />
            ),
        },
        {
            title: 'Example type',
            key: 'type',
            dataIndex: 'samples',
            width: '200px',
            render: (samples: { type: string; value: string }[]) =>
                samples.length > 0 ? samples[0].type : <span className="text-muted italic">No exception types</span>,
        },
        {
            title: 'Example message',
            key: 'message',
            dataIndex: 'samples',
            render: (messages: { type: string; value: string }[]) =>
                messages.length > 0 ? (
                    messages[0].value
                ) : (
                    <span className="text-muted italic">No exception messages</span>
                ),
        },
        { title: 'Count', dataIndex: 'count' },
    ] as LemonTableColumns<ErrorTrackingFingerprintSamples>

    const disabledReason =
        selectedFingerprints.length === fingerprintSamples.length
            ? 'You must leave at least one fingerprint associated with the issue'
            : selectedFingerprints.length === 0
              ? 'Select at least one fingerprint'
              : fingerprintSamples.length === 1
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
                <LemonTable<ErrorTrackingFingerprintSamples>
                    className="w-full"
                    loading={isLoading}
                    dataSource={fingerprintSamples}
                    columns={columns}
                    expandable={{
                        noIndent: true,
                        rowExpandable: (record) => record.samples.length > 1,
                        expandedRowRender: (record) => (
                            <LemonTable
                                className="w-full"
                                loading={false}
                                embedded={true}
                                showHeader={true}
                                dataSource={record.samples}
                                columns={[
                                    { title: 'Type', width: '200px', dataIndex: 'type' },
                                    { title: 'Message', dataIndex: 'value' },
                                ]}
                            />
                        ),
                    }}
                />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}
