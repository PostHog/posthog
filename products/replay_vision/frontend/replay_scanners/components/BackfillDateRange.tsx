import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'

import { DateMappingOption } from '~/types'

import { backfillsLogic, isBackfillActive } from '../backfillsLogic'
import { BackfillCostEstimate } from './BackfillCostEstimate'
import { BackfillHistoryTable } from './BackfillHistoryTable'

// Hour-scale presets matter as much as day-scale ones: a common case is re-scanning the last couple
// of hours after fixing a prompt, not re-scanning a month.
const BACKFILL_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 3 hours', values: ['-3h'] },
    { key: 'Last 6 hours', values: ['-6h'] },
    { key: 'Last 24 hours', values: ['-24h'] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 30 days', values: ['-30d'] },
    { key: 'Last 90 days', values: ['-90d'] },
]

export function BackfillDateRange({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = backfillsLogic({ scannerId })
    const { backfills, estimate, estimateLoading, creatingBackfill, windowDateFrom, windowDateTo } = useValues(logic)
    const { createBackfill, setWindowRange } = useActions(logic)

    const activeBackfill = backfills.find(isBackfillActive)

    const startDisabledReason = activeBackfill
        ? 'This scanner already has an active backfill'
        : !estimate
          ? 'Pick a time range to see the cost first'
          : estimate.total_sessions === 0
            ? 'No eligible sessions in this time range'
            : undefined

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-5">
                <p className="text-muted text-sm m-0">
                    Scan every recording in a date range that matches this scanner's filters, including ones from before
                    you created it. Recordings it already scanned are skipped, so you aren't charged twice. It uses the
                    scanner's settings as they are now, so editing the scanner later won't change a backfill that's
                    already running.
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                    <DateFilter
                        size="small"
                        dateFrom={windowDateFrom}
                        dateTo={windowDateTo}
                        dateOptions={BACKFILL_DATE_OPTIONS}
                        onChange={(dateFrom, dateTo) => setWindowRange(dateFrom, dateTo)}
                        allowTimePrecision
                        allowFixedRangeWithTime
                        allowedRollingDateOptions={['hours', 'days', 'weeks', 'months']}
                        data-attr="vision-backfill-date-filter"
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => estimate && createBackfill(estimate.window_start, estimate.window_end)}
                        loading={creatingBackfill}
                        disabledReason={startDisabledReason}
                        data-attr="vision-backfill-start"
                    >
                        Start backfill
                    </LemonButton>
                </div>
                <BackfillCostEstimate estimate={estimate} loading={estimateLoading} />
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="text-sm font-medium m-0">Backfill history</h3>
                <BackfillHistoryTable scannerId={scannerId} />
            </div>
        </div>
    )
}
