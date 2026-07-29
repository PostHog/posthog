import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterEntry } from 'lib/components/TaxonomicFilter/menu'
import { TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu/TaxonomicFilterMenu'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Button, SelectTriggerIcon } from 'lib/ui/quill'

import { DateRangeButton } from '../DateRangeButton'
import { InternalAccountsToggle } from '../InternalAccountsToggle'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BreakdownsEvents, TAXONOMIC_GROUP_TYPES } from './consts'

export function BreakdownsSearchBar(): JSX.Element {
    const { dateRange, filterTestAccounts, breakdownProperty } = useValues(breakdownFiltersLogic)
    const { setDateRange, setFilterTestAccounts, setBreakdownProperty } = useActions(breakdownFiltersLogic)

    /*
     * Synthetic entry for the current property. The menu reads `group.type` to route the
     * initial open — with it set the picker lands straight on the searchable property list
     * with this property highlighted, rather than the category menu. A full
     * `TaxonomicFilterGroup` isn't needed; the orchestrator resolves the real one on commit.
     */
    const selected = useMemo<MenuFilterEntry>(
        () =>
            ({
                item: { id: breakdownProperty, name: breakdownProperty },
                group: {
                    type: TaxonomicFilterGroupType.EventProperties,
                    getName: (item: any) => item?.name,
                    getValue: (item: any) => item?.name ?? item?.id,
                },
                name: breakdownProperty,
            }) as unknown as MenuFilterEntry,
        [breakdownProperty]
    )

    return (
        <div className="flex items-center flex-wrap px-2 py-2 gap-1">
            <DateRangeButton dateRange={dateRange} onChange={setDateRange} />
            <TaxonomicFilterHeadless.Root
                className="contents"
                bindRootProps={false}
                groupType={TaxonomicFilterGroupType.EventProperties}
                taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                value={breakdownProperty}
                onChange={(_, value) => {
                    if (value) {
                        setBreakdownProperty(String(value))
                        posthog.capture(BreakdownsEvents.PropertySelected, {
                            property: String(value),
                        })
                    }
                }}
            >
                <TaxonomicFilterMenu
                    selected={selected}
                    trigger={({ open }) => (
                        <Button variant="outline" size="default" aria-expanded={open} data-attr="breakdown-property">
                            <PropertyKeyInfo
                                value={breakdownProperty}
                                disablePopover
                                type={TaxonomicFilterGroupType.EventProperties}
                            />
                            <SelectTriggerIcon />
                        </Button>
                    )}
                />
            </TaxonomicFilterHeadless.Root>
            <div className="ml-auto shrink-0">
                <InternalAccountsToggle
                    filterTestAccounts={filterTestAccounts}
                    onChange={setFilterTestAccounts}
                    id="error-tracking-breakdowns-test-account-filter"
                />
            </div>
        </div>
    )
}
