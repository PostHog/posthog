import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover'
import { dateMapping } from 'lib/utils'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BreakdownsEvents, TAXONOMIC_GROUP_TYPES } from './consts'

export function BreakdownsSearchBar(): JSX.Element {
    const { dateRange, filterTestAccounts, filterOpen, breakdownProperty } = useValues(breakdownFiltersLogic)
    const { setDateRange, setFilterTestAccounts, setFilterOpen, setBreakdownProperty } =
        useActions(breakdownFiltersLogic)

    return (
        <div className="border rounded bg-surface-primary p-3 flex gap-2 items-center">
            <DateFilter
                size="small"
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                fullWidth={false}
                dateOptions={dateMapping}
                onChange={(changedDateFrom, changedDateTo) => {
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }}
                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
            />
            <Popover
                overlay={
                    <TaxonomicFilter
                        value={breakdownProperty}
                        onChange={(_, value) => {
                            if (value) {
                                setBreakdownProperty(String(value))
                                posthog.capture(BreakdownsEvents.PropertySelected, {
                                    property: String(value),
                                })
                            }
                            setFilterOpen(false)
                        }}
                        taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                    />
                }
                visible={filterOpen}
                onClickOutside={() => setFilterOpen(false)}
            >
                <LemonButton size="small" type="secondary" onClick={() => setFilterOpen(!filterOpen)}>
                    <PropertyKeyInfo
                        value={breakdownProperty}
                        disablePopover
                        type={TaxonomicFilterGroupType.EventProperties}
                    />
                </LemonButton>
            </Popover>
            <div className="flex-1" />
            <div>
                <TestAccountFilter
                    size="small"
                    filters={{ filter_test_accounts: filterTestAccounts }}
                    onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts || false)}
                />
            </div>
        </div>
    )
}
