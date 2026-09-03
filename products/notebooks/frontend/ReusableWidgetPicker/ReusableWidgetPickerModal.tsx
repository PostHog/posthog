import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { collectNotebookFrameNodes } from 'scenes/notebooks/Nodes/notebookNodeContent'

import { reusableWidgetCatalogLogic } from '../ReusableWidgetCatalog/reusableWidgetCatalogLogic'
import { ReusableWidgetPickerLogicProps, reusableWidgetPickerLogic } from './reusableWidgetPickerLogic'

export function ReusableWidgetPickerModal(props: ReusableWidgetPickerLogicProps): JSX.Element {
    const logic = useMountedLogic(reusableWidgetPickerLogic(props))
    const catalogLogic = useMountedLogic(reusableWidgetCatalogLogic)
    const {
        attachError,
        attachInFlight,
        bindings,
        pickerOpen,
        selectedWidget,
        selectedWidgetError,
        selectedWidgetLoading,
    } = useValues(logic)
    const { reusableWidgets, reusableWidgetsError, reusableWidgetsResponseLoading, search } = useValues(catalogLogic)
    const { attachReusableWidget, closePicker, selectReusableWidget, setBindingHog, setBindingSource, showCatalog } =
        useActions(logic)
    const { loadReusableWidgets, setSearch } = useActions(catalogLogic)
    const frames = collectNotebookFrameNodes(props.getContent()).filter((frame) => frame.hasRun)

    useEffect(() => {
        if (pickerOpen) {
            loadReusableWidgets()
        }
    }, [loadReusableWidgets, pickerOpen])

    return (
        <LemonModal
            isOpen={pickerOpen}
            onClose={closePicker}
            title={selectedWidget ? `Add ${selectedWidget.name}` : 'Add a reusable widget'}
            width="min(48rem, 90vw)"
            footer={
                selectedWidget ? (
                    <>
                        <LemonButton onClick={showCatalog}>Back</LemonButton>
                        <LemonButton type="primary" onClick={attachReusableWidget} loading={attachInFlight}>
                            Add to notebook
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton onClick={closePicker}>Close</LemonButton>
                )
            }
        >
            {selectedWidgetLoading ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-8 w-1/2" />
                    <LemonSkeleton className="h-40 w-full" />
                </div>
            ) : selectedWidget ? (
                <div className="flex flex-col gap-4">
                    <div className="text-secondary">{selectedWidget.description || 'Reusable notebook widget'}</div>
                    {selectedWidget.current_version.frame_names.length ? (
                        <LemonBanner type="info">
                            Map each reusable input to a dataframe in this notebook. Add a Hog expression only when the
                            source needs reshaping. Hog receives <code>rows</code>, <code>columns</code>, and{' '}
                            <code>frame</code> and must return a list of objects.
                        </LemonBanner>
                    ) : null}
                    {selectedWidget.current_version.frame_names.map((slot) => (
                        <div key={slot} className="rounded border p-3">
                            <div className="mb-3 flex items-center gap-2">
                                <span className="font-semibold">{slot}</span>
                                <LemonTag size="small">Input</LemonTag>
                            </div>
                            <div className="mb-3 flex flex-wrap gap-1">
                                {selectedWidget.current_version.input_contract
                                    .find((input) => input.slot === slot)
                                    ?.columns?.map((column) => (
                                        <LemonTag key={column.name} size="small">
                                            {column.name}: {column.type}
                                        </LemonTag>
                                    ))}
                            </div>
                            <div className="flex flex-col gap-3">
                                <div>
                                    <LemonLabel>Notebook dataframe</LemonLabel>
                                    <LemonSelect
                                        value={bindings[slot]?.source || undefined}
                                        options={frames.map((frame) => ({
                                            value: frame.name,
                                            label: `${frame.name} (${frame.columns.length} columns)`,
                                        }))}
                                        onChange={(source) => setBindingSource(slot, source)}
                                        placeholder="Choose a dataframe"
                                        fullWidth
                                    />
                                </div>
                                <div>
                                    <LemonLabel>Hog mapping (optional)</LemonLabel>
                                    <LemonTextArea
                                        value={bindings[slot]?.hog ?? ''}
                                        onChange={(hog) => setBindingHog(slot, hog)}
                                        placeholder="return rows"
                                        minRows={3}
                                        className="font-mono ph-no-capture"
                                    />
                                </div>
                            </div>
                        </div>
                    ))}
                    {attachError ? <LemonBanner type="error">{attachError}</LemonBanner> : null}
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    <LemonInput
                        type="search"
                        value={search}
                        onChange={setSearch}
                        placeholder="Search reusable widgets"
                        autoFocus
                    />
                    {reusableWidgetsError || selectedWidgetError ? (
                        <LemonBanner type="error" action={{ children: 'Retry', onClick: loadReusableWidgets }}>
                            {selectedWidgetError || "We couldn't load reusable widgets."}
                        </LemonBanner>
                    ) : null}
                    {reusableWidgetsResponseLoading ? (
                        <LemonSkeleton className="h-40 w-full" />
                    ) : reusableWidgets.length ? (
                        <div className="flex max-h-[28rem] flex-col divide-y overflow-auto rounded border">
                            {reusableWidgets.map((widget) => (
                                <LemonButton
                                    key={widget.id}
                                    type="tertiary"
                                    fullWidth
                                    className="justify-start rounded-none p-3 text-left"
                                    onClick={() => selectReusableWidget(widget.id)}
                                >
                                    <span className="flex flex-col items-start gap-1">
                                        <span className="font-semibold">{widget.name}</span>
                                        {widget.description ? (
                                            <span className="text-sm text-secondary">{widget.description}</span>
                                        ) : null}
                                    </span>
                                </LemonButton>
                            ))}
                        </div>
                    ) : (
                        <div className="rounded border p-6 text-center text-secondary">No reusable widgets found.</div>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
