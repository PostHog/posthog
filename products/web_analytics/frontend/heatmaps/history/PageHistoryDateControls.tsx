import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { isUsableCapture, pageHistoryLogic } from './pageHistoryLogic'
import { formatCaptureDay, formatHistoryDateRange } from './pageHistoryUtils'

export function PageHistoryDateControls({ id }: { id: string }): JSX.Element {
    const logic = pageHistoryLogic({ id })
    const {
        captures,
        selectedBackground,
        selectedDateRange,
        isCombinedRange,
        previousCapture,
        nextCapture,
        historyBrowseDisabledReason,
    } = useValues(logic)
    const { browseCapture, navigateCapture, openRangeEditor } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center gap-1" aria-label="Historical interaction dates">
            {isCombinedRange && selectedDateRange ? (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={openRangeEditor}
                    disabledReason={historyBrowseDisabledReason}
                    data-attr="heatmap-page-history-range"
                >
                    {formatHistoryDateRange(selectedDateRange)}
                </LemonButton>
            ) : (
                <>
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={() => navigateCapture('previous')}
                        aria-label={
                            previousCapture
                                ? `Previous available capture: ${formatCaptureDay(previousCapture.captured_on, 'long')}`
                                : 'Previous available capture'
                        }
                        disabledReason={
                            historyBrowseDisabledReason ||
                            (!previousCapture ? 'This is the oldest available screenshot.' : undefined)
                        }
                        tooltip={
                            previousCapture ? `Inspect ${formatCaptureDay(previousCapture.captured_on)}` : undefined
                        }
                        data-attr="heatmap-page-history-previous-day"
                    />
                    <LemonSelect
                        size="small"
                        value={selectedBackground?.id}
                        onSelect={browseCapture}
                        aria-label="Historical interaction day"
                        disabledReason={historyBrowseDisabledReason}
                        options={[...captures].reverse().map((capture) => ({
                            value: capture.id,
                            label: `${formatCaptureDay(capture.captured_on)}${isUsableCapture(capture) ? '' : ' (no screenshot)'}`,
                        }))}
                        data-attr="heatmap-page-history-dates"
                    />
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        onClick={() => navigateCapture('next')}
                        aria-label={
                            nextCapture
                                ? `Next available capture: ${formatCaptureDay(nextCapture.captured_on, 'long')}`
                                : 'Next available capture'
                        }
                        disabledReason={
                            historyBrowseDisabledReason ||
                            (!nextCapture ? 'This is the newest available screenshot.' : undefined)
                        }
                        tooltip={nextCapture ? `Inspect ${formatCaptureDay(nextCapture.captured_on)}` : undefined}
                        data-attr="heatmap-page-history-next-day"
                    />
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={openRangeEditor}
                        disabledReason={historyBrowseDisabledReason}
                        data-attr="heatmap-page-history-combine"
                    >
                        Combine days
                    </LemonButton>
                </>
            )}
        </div>
    )
}
