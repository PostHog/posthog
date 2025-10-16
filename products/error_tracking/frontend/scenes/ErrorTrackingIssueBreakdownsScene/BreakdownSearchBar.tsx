import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { errorTrackingBreakdownsSceneLogic } from './errorTrackingBreakdownsSceneLogic'

export function BreakdownSearchBar(): JSX.Element {
    const { dateRange, filterTestAccounts } = useValues(breakdownFiltersLogic)
    const { setDateRange, setFilterTestAccounts } = useActions(breakdownFiltersLogic)
    const { selectedBreakdownPreset } = useValues(errorTrackingBreakdownsSceneLogic)

    return (
        <div className="border rounded bg-surface-primary p-3 flex flex-col gap-3">
            <div className="text-base font-semibold">Group by "{selectedBreakdownPreset.title}"</div>
            <div className="flex gap-2 justify-between">
                <DateFilter
                    size="small"
                    dateFrom={dateRange.date_from}
                    dateTo={dateRange.date_to}
                    fullWidth={false}
                    dateOptions={dateMapping}
                    onChange={(changedDateFrom, changedDateTo) =>
                        setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                    }
                    allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                />
                <div>
                    <TestAccountFilter
                        size="small"
                        filters={{ filter_test_accounts: filterTestAccounts }}
                        onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts || false)}
                    />
                </div>
            </div>
        </div>
    )
}
