import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { pageHistoryLogic } from './pageHistoryLogic'
import { formatCaptureDay } from './pageHistoryUtils'

export function PageHistoryDateControls({ id }: { id: string }): JSX.Element {
    const logic = pageHistoryLogic({ id })
    const { usableCaptures, selectedDateRange, isCombinedRange, historyBrowseDisabledReason } = useValues(logic)
    const { browseCapture, openRangeEditor } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center gap-1" aria-label="Historical interaction dates">
            <div data-attr={isCombinedRange ? 'heatmap-page-history-range' : 'heatmap-page-history-dates'}>
                <DateFilter
                    type="tertiary"
                    dateFrom={selectedDateRange?.date_from}
                    dateTo={isCombinedRange ? selectedDateRange?.date_to : null}
                    isFixedDateMode={!isCombinedRange}
                    dateOptions={[...usableCaptures].reverse().map((capture) => ({
                        key: formatCaptureDay(capture.captured_on),
                        values: [capture.captured_on],
                    }))}
                    showCustomRangeOptions={false}
                    showRollingRangePicker={false}
                    disabledReason={historyBrowseDisabledReason}
                    onChange={(fromDate) => {
                        const capture = usableCaptures.find((capture) => capture.captured_on === fromDate)
                        if (capture) {
                            browseCapture(capture.id)
                        }
                    }}
                />
            </div>
            <LemonButton
                size="small"
                type="tertiary"
                onClick={openRangeEditor}
                disabledReason={historyBrowseDisabledReason}
                data-attr="heatmap-page-history-combine"
            >
                Combine days
            </LemonButton>
        </div>
    )
}
