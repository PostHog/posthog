import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'

import { DateMappingOption } from '~/types'

import { FilterPill } from '../../components/FilterPill'
import type { ObservationVerdictValue } from '../replayScannerLogic'
import { scannerOverviewLogic } from '../scannerOverviewLogic'

const VERDICT_OPTIONS: { value: ObservationVerdictValue; label: string }[] = [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'inconclusive', label: 'Inconclusive' },
]

// Empty values on "All time" clear the range; mirrors the observations table's options.
const OVERVIEW_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'All time', values: [] },
    { key: 'Last 24 hours', values: ['-24h'] },
    { key: 'Last 3 days', values: ['-3d'] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 14 days', values: ['-14d'] },
    { key: 'Last 30 days', values: ['-30d'] },
    { key: 'Last 90 days', values: ['-90d'] },
]

/** The Overview tab's own filter bar, independent of the Observations list filters. Drives the charts
 * and stat panels via scannerOverviewLogic. Type-specific pills show only where they apply. */
export function ScannerOverviewFilters({ scannerId }: { scannerId: string }): JSX.Element {
    const {
        scanner,
        overviewDateFrom,
        overviewDateTo,
        overviewVerdictFilter,
        overviewTagFilter,
        availableTags,
        hasActiveOverviewFilters,
    } = useValues(scannerOverviewLogic({ scannerId }))
    const { setOverviewDateRange, setOverviewVerdictFilter, setOverviewTagFilter, clearOverviewFilters } = useActions(
        scannerOverviewLogic({ scannerId })
    )

    const scannerType = scanner?.scanner_type
    const tagOptions = availableTags.map((tag) => ({ value: tag, label: tag }))

    return (
        <div className="flex flex-wrap items-center gap-2">
            <DateFilter
                size="small"
                dateFrom={overviewDateFrom}
                dateTo={overviewDateTo}
                dateOptions={OVERVIEW_DATE_OPTIONS}
                onChange={(dateFrom, dateTo) => setOverviewDateRange(dateFrom, dateTo)}
            />
            {scannerType === 'monitor' && (
                <FilterPill<ObservationVerdictValue>
                    label="Verdict"
                    options={VERDICT_OPTIONS}
                    value={overviewVerdictFilter}
                    onChange={setOverviewVerdictFilter}
                />
            )}
            {scannerType === 'classifier' && tagOptions.length > 0 && (
                <FilterPill<string>
                    label="Tag"
                    options={tagOptions}
                    value={overviewTagFilter}
                    onChange={setOverviewTagFilter}
                    searchable
                />
            )}
            <LemonButton
                type="tertiary"
                size="small"
                onClick={() => clearOverviewFilters()}
                disabledReason={hasActiveOverviewFilters ? undefined : 'No active filters'}
                data-attr="vision-overview-clear-filters"
            >
                Clear filters
            </LemonButton>
        </div>
    )
}
