import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { ReusableWidgetDemoDataLogicProps, reusableWidgetDemoDataLogic } from './reusableWidgetDemoDataLogic'

export function ReusableWidgetDemoDataModal(props: ReusableWidgetDemoDataLogicProps): JSX.Element {
    const logic = reusableWidgetDemoDataLogic(props)
    const {
        demoFrame,
        demoFrameLoading,
        loadError,
        selectedInput,
        editing,
        draftJSON,
        validation,
        hasChanges,
        savedFrameLoading,
        saveError,
    } = useValues(logic)
    const { selectInput, startEditing, cancelEditing, setDraftJSON, requestClose, loadDemoFrame, saveDemoData } =
        useActions(logic)
    const hasInputs = props.version.input_contract.length > 0

    return (
        <LemonModal
            isOpen
            onClose={requestClose}
            title={`Demo data · Version ${props.version.version}`}
            width="70vw"
            footer={
                <>
                    <LemonButton onClick={requestClose} disabled={savedFrameLoading}>
                        Close
                    </LemonButton>
                    {editing ? (
                        <>
                            <LemonButton onClick={cancelEditing} disabled={savedFrameLoading}>
                                Cancel edits
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={saveDemoData}
                                loading={savedFrameLoading}
                                disabledReason={
                                    validation.error || (!hasChanges ? 'Edit the demo rows before saving.' : undefined)
                                }
                                data-attr="reusable-widget-save-demo-data"
                            >
                                Save demo data
                            </LemonButton>
                        </>
                    ) : props.canEdit && hasInputs ? (
                        <LemonButton
                            type="primary"
                            onClick={startEditing}
                            disabled={demoFrameLoading || !!loadError || !demoFrame}
                            data-attr="reusable-widget-edit-demo-data"
                        >
                            Edit demo data
                        </LemonButton>
                    ) : null}
                </>
            }
        >
            <div className="flex min-w-0 flex-col gap-3">
                <p className="m-0 text-secondary">
                    Saved sample rows used by this version's preview. Editing them does not change notebook data or the
                    widget's input contract.
                </p>
                {!props.canEdit ? (
                    <LemonBanner type="info">To edit demo data, select the latest version or its draft.</LemonBanner>
                ) : null}
                {!hasInputs ? (
                    <p>This widget does not use dataframe inputs, so it has no demo data to edit.</p>
                ) : (
                    <>
                        <LemonSelect
                            aria-label="Demo input"
                            value={selectedInput}
                            options={props.version.input_contract.map((input) => ({
                                value: input.slot,
                                label: input.slot,
                            }))}
                            onChange={selectInput}
                            disabledReason={editing ? 'Save or cancel your edits before switching inputs.' : undefined}
                            data-attr="reusable-widget-demo-input"
                        />
                        {demoFrameLoading ? (
                            <LemonSkeleton className="h-64 w-full" />
                        ) : loadError ? (
                            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDemoFrame }}>
                                We couldn't load the saved demo data.
                            </LemonBanner>
                        ) : demoFrame ? (
                            editing ? (
                                <>
                                    <p className="m-0 text-sm text-secondary">
                                        Enter an array of objects, one per row, using the column names below. Save up to
                                        20 rows per input.
                                    </p>
                                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-secondary">
                                        {demoFrame.columns.map((column) => (
                                            <span key={column.name}>
                                                {column.name}: {column.type}
                                            </span>
                                        ))}
                                    </div>
                                    <CodeEditorResizeable
                                        className="ph-no-capture"
                                        language="json"
                                        value={draftJSON}
                                        onChange={(text) => setDraftJSON(text ?? '')}
                                        minHeight="20rem"
                                        maxHeight="55vh"
                                        allowManualResize={false}
                                        options={{ readOnly: savedFrameLoading, minimap: { enabled: false } }}
                                    />
                                    {validation.error ? (
                                        <LemonBanner type="error">{validation.error}</LemonBanner>
                                    ) : null}
                                    {saveError ? <LemonBanner type="error">{saveError}</LemonBanner> : null}
                                </>
                            ) : (
                                <>
                                    <div className="text-sm text-secondary">
                                        {demoFrame.rows.length} saved {demoFrame.rows.length === 1 ? 'row' : 'rows'}
                                        {demoFrame.truncated ? ` (sample of ${demoFrame.totalRowCount} rows)` : ''}
                                    </div>
                                    <div className="max-h-96 overflow-auto ph-no-capture">
                                        <LemonTable
                                            dataSource={demoFrame.rows.map((cells, index) => ({ cells, index }))}
                                            rowKey="index"
                                            columns={demoFrame.columns.map((column, index) => ({
                                                key: column.name,
                                                title: column.name,
                                                tooltip: column.type,
                                                render: (_, row) => {
                                                    const value = row.cells[index]
                                                    return (
                                                        <span className="break-all">
                                                            {typeof value === 'string' ? value : JSON.stringify(value)}
                                                        </span>
                                                    )
                                                },
                                            }))}
                                            emptyState="No saved rows for this input."
                                            size="small"
                                        />
                                    </div>
                                </>
                            )
                        ) : null}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
