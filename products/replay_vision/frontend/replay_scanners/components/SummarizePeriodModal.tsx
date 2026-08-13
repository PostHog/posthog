import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'

import { DateMappingOption } from '~/types'

import { scannerDigestLogic } from '../scannerDigestLogic'

// Day-scale presets: a period summary rolls up days or weeks of findings, unlike backfills where
// hour-scale re-scans matter.
const PERIOD_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 24 hours', values: ['-24h'] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 14 days', values: ['-14d'] },
    { key: 'Last 30 days', values: ['-30d'] },
    { key: 'Last 90 days', values: ['-90d'] },
]

/** Picks the observation window for a one-off digest run over a chosen period, e.g. a whole
 * backfill, instead of the digest's usual "everything since the last run". */
export function SummarizePeriodModal({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element {
    const logic = scannerDigestLogic({ scannerId, scannerName })
    const { periodModalOpen, periodDateFrom, periodDateTo, summarizingPeriod, runInProgress } = useValues(logic)
    const { closePeriodModal, setPeriodRange, summarizePeriod } = useActions(logic)

    return (
        <LemonModal
            isOpen={periodModalOpen}
            onClose={closePeriodModal}
            title="Summarize a period"
            description="Generate a one-off summary of everything this scanner found in a period. The recurring digest and its schedule stay unchanged."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closePeriodModal} data-attr="vision-digest-period-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={summarizePeriod}
                        loading={summarizingPeriod}
                        disabledReason={runInProgress ? 'A run is already in progress' : undefined}
                        data-attr="vision-digest-period-generate"
                    >
                        Generate summary
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <DateFilter
                    dateFrom={periodDateFrom}
                    dateTo={periodDateTo}
                    dateOptions={PERIOD_DATE_OPTIONS}
                    onChange={(dateFrom, dateTo) => setPeriodRange(dateFrom, dateTo)}
                    data-attr="vision-digest-period-date-filter"
                />
                <p className="text-muted text-xs mb-0">
                    When a period holds more observations than fit one summary, an even sample across the period is
                    summarized, and the summary says so.
                </p>
            </div>
        </LemonModal>
    )
}
