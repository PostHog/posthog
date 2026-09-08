import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { collectNotebookFrameNodes } from 'scenes/notebooks/Nodes/notebookNodeContent'

import { reusableWidgetCatalogLogic } from '../ReusableWidgetCatalog/reusableWidgetCatalogLogic'
import { ReusableWidgetInputMapping } from './ReusableWidgetInputMapping'
import { ReusableWidgetPickerLogicProps, reusableWidgetPickerLogic } from './reusableWidgetPickerLogic'

export function ReusableWidgetPickerModal(props: ReusableWidgetPickerLogicProps): JSX.Element {
    const logic = useMountedLogic(reusableWidgetPickerLogic(props))
    const catalogLogic = useMountedLogic(reusableWidgetCatalogLogic)
    const {
        attachError,
        attachInFlight,
        aiHandoffInFlight,
        attachDisabledReason,
        pickerOpen,
        selectedWidget,
        selectedWidgetError,
        selectedWidgetLoading,
    } = useValues(logic)
    const { reusableWidgets, reusableWidgetsError, reusableWidgetsResponseLoading, search } = useValues(catalogLogic)
    const { attachReusableWidget, closePicker, selectReusableWidget, showCatalog } = useActions(logic)
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
            onClose={attachInFlight ? undefined : closePicker}
            title={selectedWidget ? `Add ${selectedWidget.name}` : 'Add a reusable widget'}
            width="min(48rem, 90vw)"
            footer={
                selectedWidget ? (
                    <>
                        <LemonButton
                            onClick={showCatalog}
                            disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={attachReusableWidget}
                            loading={attachInFlight && !aiHandoffInFlight}
                            disabledReason={aiHandoffInFlight ? 'Opening AI…' : attachDisabledReason}
                        >
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
                        <p className="mb-0 text-secondary">
                            Choose a dataframe for each input. Matching columns connect automatically.
                        </p>
                    ) : null}
                    {!frames.length && selectedWidget.current_version.frame_names.length ? (
                        <LemonBanner type="info">
                            Run a SQL or Python cell that returns a dataframe, then reopen this picker.
                        </LemonBanner>
                    ) : null}
                    {selectedWidget.current_version.frame_names.map((slot) => (
                        <ReusableWidgetInputMapping
                            key={slot}
                            logicProps={props}
                            slot={slot}
                            columns={
                                selectedWidget.current_version.input_contract.find((input) => input.slot === slot)
                                    ?.columns ?? []
                            }
                            frames={frames}
                        />
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
