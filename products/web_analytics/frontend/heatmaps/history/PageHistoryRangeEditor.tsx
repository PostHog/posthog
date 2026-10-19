import { useActions, useValues } from 'kea'

import { IconCamera } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { isUsableCapture, pageHistoryLogic } from './pageHistoryLogic'
import { formatCaptureDay, formatCaptureTimestamp, formatHistoryDateRange } from './pageHistoryUtils'

export function PageHistoryRangeEditor({ id }: { id: string }): JSX.Element | null {
    const logic = pageHistoryLogic({ id })
    const { rangeEditorOpen, rangeDraft, rangeDraftBackground, rangeDraftCaptures, rangeDraftError, captures } =
        useValues(logic)
    const { setRangeEditorOpen, setRangeDraft, applyRangeDraft } = useActions(logic)
    if (!rangeEditorOpen) {
        return null
    }
    const options = captures.map((capture) => ({
        value: capture.id,
        label: formatCaptureDay(capture.captured_on),
        disabledReason: !isUsableCapture(capture) ? 'No screenshot is available for this date.' : undefined,
    }))

    return (
        <LemonModal
            isOpen={rangeEditorOpen}
            onClose={() => setRangeEditorOpen(false)}
            title="Combine interaction days"
            width={480}
            footer={
                <div className="flex justify-end gap-2">
                    <LemonButton type="secondary" onClick={() => setRangeEditorOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={applyRangeDraft}
                        disabledReason={rangeDraftError}
                        data-attr="heatmap-page-history-apply-range"
                    >
                        Apply
                    </LemonButton>
                </div>
            }
            data-attr="heatmap-page-history-range-editor"
        >
            <div className="grid grid-cols-2 gap-3 mb-4">
                <div>
                    <LemonLabel htmlFor="heatmap-history-from">From</LemonLabel>
                    <LemonSelect
                        id="heatmap-history-from"
                        aria-label="History range start"
                        options={options}
                        value={rangeDraft?.fromId}
                        onChange={(value) => setRangeDraft(value, rangeDraft?.toId ?? value)}
                    />
                </div>
                <div>
                    <LemonLabel htmlFor="heatmap-history-to">To</LemonLabel>
                    <LemonSelect
                        id="heatmap-history-to"
                        aria-label="History range end"
                        options={options}
                        value={rangeDraft?.toId}
                        onChange={(value) => setRangeDraft(rangeDraft?.fromId ?? value, value)}
                    />
                </div>
            </div>
            {rangeDraftBackground ? (
                <div
                    className="rounded border bg-surface-secondary p-3 mb-4"
                    data-attr="heatmap-page-history-range-preview"
                >
                    <strong>
                        <span>{`Interactions: ${formatHistoryDateRange({ date_from: rangeDraftCaptures[0].captured_on, date_to: rangeDraftBackground.captured_on })}`}</span>
                    </strong>
                    <div className="flex items-center gap-3 mt-2">
                        <div className="relative w-32 h-24 shrink-0 rounded bg-surface-primary flex items-center justify-center overflow-hidden">
                            <IconCamera className="text-muted text-xl" />
                            {rangeDraftBackground.thumbnail_url ? (
                                <img
                                    key={rangeDraftBackground.thumbnail_url}
                                    src={rangeDraftBackground.thumbnail_url}
                                    alt={`Screenshot preview for ${formatCaptureDay(rangeDraftBackground.captured_on, 'long')}`}
                                    className="absolute inset-0 w-full h-full object-cover object-top"
                                    onError={(event) => {
                                        event.currentTarget.hidden = true
                                    }}
                                />
                            ) : null}
                        </div>
                        <div className="min-w-0 text-sm">
                            <span>{`Screenshot used: ${formatCaptureTimestamp(rangeDraftBackground)}`}</span>
                            <p className="text-xs text-muted mb-0 mt-1">
                                <span>{`Newest available screenshot in this period · ${rangeDraftBackground.width}px`}</span>
                            </p>
                        </div>
                    </div>
                </div>
            ) : (
                <LemonBanner type="warning" className="mb-3">
                    {rangeDraftError}
                </LemonBanner>
            )}
            <LemonBanner type="warning">
                Page changes may misalign clicks across these days. View individual days if the layout changed.
            </LemonBanner>
        </LemonModal>
    )
}
