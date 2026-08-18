import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { teamLogic } from 'scenes/teamLogic'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { LogsDateRangePicker } from '../LogsDateRangePicker/LogsDateRangePicker'

const taxonomicFilterLogicKey = 'logs'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Logs,
    TaxonomicFilterGroupType.LogResourceAttributes,
    TaxonomicFilterGroupType.LogAttributes,
]

/**
 * Time range, zoom and refresh — the always-relevant "execute the query" controls of the query bar.
 * Live tail lives in the results bar instead (LogsViewerToolbar): it's the one streaming control we
 * deliberately place with the Logs-only tools so it hides cleanly with that cluster in Patterns mode,
 * rather than collapsing in this top bar and shifting its layout.
 */
export const LogsQueryControls = (): JSX.Element => {
    const { logsLoading, liveTailRunning } = useValues(logsViewerDataLogic)
    const { runQuery } = useActions(logsViewerDataLogic)
    const { setDateRange } = useActions(logsViewerFiltersLogic)
    const { filters } = useValues(logsViewerFiltersLogic)
    const { dateRange } = filters

    return (
        <div className="flex shrink-0 gap-1.5">
            <LogsDateRangePicker dateRange={dateRange} setDateRange={setDateRange} />

            <LemonButton
                size="small"
                icon={<IconRefresh />}
                type="secondary"
                onClick={() => runQuery()}
                loading={logsLoading || liveTailRunning}
                disabledReason={liveTailRunning ? 'Disable live tail to manually refresh' : undefined}
            />
        </div>
    )
}

export const LogsFilterGroup = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { filters, id, utcDateRange, queryFilterGroup } = useValues(logsViewerFiltersLogic)
    const { filterGroup } = filters
    const { setFilterGroup } = useActions(logsViewerFiltersLogic)

    // Taxonomic value suggestions should respect any active scope (e.g. the person-tab
    // distinct_id pin), so pass the combined query view rather than the user-editable
    // filterGroup. The UniversalFilters `group` prop stays on the editable filterGroup
    // so chips reflect what the user can actually edit.
    const endpointFilters = {
        dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
        filterGroup: queryFilterGroup,
    }

    return (
        <UniversalFilters
            rootKey={`${taxonomicFilterLogicKey}-${id}`}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            endpointFilters={endpointFilters}
            onChange={(group) => {
                setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })
            }}
        >
            {children}
        </UniversalFilters>
    )
}

/**
 * Handles selecting a taxonomic item that carries its own value — notably the Logs group's free-text
 * `Search log message for "…"` item, whose value lives on `item.value` rather than in the `value`
 * argument (the Logs group's `getValue` returns the key, `message`).
 *
 * Besides building the filter, this records the *complete* filter to recents itself. taxonomicFilterLogic
 * records the selection too, but it strips the item down to `{ name }` and only carries a propertyFilter
 * through for items that already came from recents — so its record would drop the searched-for value, and
 * re-selecting the entry from "Recent" would yield a bare `message` with nothing to match on.
 *
 * We mirror its groupType/value exactly so both writes collide on one record rather than leaving a duplicate
 * value-less entry behind. Which of the two lands first doesn't matter: recordRecentFilter ignores a
 * value-less write when a complete record already exists, and replaces an existing value-less record when a
 * complete one arrives.
 */
export function addLogsValueFilter(
    taxonomicGroup: TaxonomicFilterGroup,
    value: TaxonomicFilterValue,
    item: any,
    currentValues: UniversalFiltersGroup['values']
): UniversalFiltersGroup['values'] {
    const newPropertyFilter = {
        key: item.key,
        value: item.value,
        operator: PropertyOperator.IContains,
        type: item.propertyFilterType,
    } as AnyPropertyFilter

    if (recentTaxonomicFiltersLogic.isMounted()) {
        recentTaxonomicFiltersLogic.actions.recordRecentFilter({
            groupType: taxonomicGroup.type,
            groupName: taxonomicGroup.name,
            value,
            // Store the key, not `item.name`. Recents are expanded for display into a bare-key row plus a
            // full-filter row, and the bare row inherits this name while dropping the value — so naming it
            // `Search log message for "foobar"` would render a row promising a value it can't apply.
            // `message` reads correctly for both rows, matching how property recents are named elsewhere.
            item: { name: item.key },
            teamId: teamLogic.findMounted()?.values.currentTeamId ?? undefined,
            propertyFilter: newPropertyFilter,
        })
    }

    return [...currentValues, newPropertyFilter]
}

export const LogsFilterSearch = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { utcDateRange, queryFilterGroup } = useValues(logsViewerFiltersLogic)
    const { addGroupFilter, setGroupValues } = useActions(universalFiltersLogic)
    const { filterGroup } = useValues(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

    const onClose = (): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey,
        taxonomicGroupTypes,
        endpointFilters: {
            dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
            filterGroup: queryFilterGroup,
        },
        onChange: (taxonomicGroup, value, item) => {
            if (item.value === undefined) {
                addGroupFilter(taxonomicGroup, value, item)
                setVisible(false)
                return
            }

            setGroupValues(addLogsValueFilter(taxonomicGroup, value, item, filterGroup.values))
            setVisible(false)
        },
        onEnter: onClose,
        autoSelectItem: true,
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px] md:w-[600px]">
                        <InfiniteSelectResults
                            focusInput={() => searchInputRef.current?.focus()}
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                            popupAnchorElement={floatingRef.current}
                        />
                    </div>
                }
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={() => onClose()}
            >
                <TaxonomicFilterSearchInput
                    onClick={() => setVisible(true)}
                    searchInputRef={searchInputRef}
                    onClose={() => onClose()}
                    onChange={() => setVisible(true)}
                />
            </LemonDropdown>
        </BindLogic>
    )
}

const FilterGroupValues = ({ allowInitiallyOpen }: { allowInitiallyOpen: boolean }): JSX.Element | null => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    if (filterGroup.values.length === 0) {
        return null
    }

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <FilterGroupValues allowInitiallyOpen={allowInitiallyOpen} />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen && filterOrGroup.type != PropertyFilterType.HogQL}
                    />
                )
            })}
        </>
    )
}

export const LogsAppliedFilters = (): JSX.Element | null => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    if (filterGroup.values.length === 0) {
        return null
    }

    return (
        <div className="flex gap-1 items-center flex-wrap">
            <FilterGroupValues allowInitiallyOpen={allowInitiallyOpen} />
        </div>
    )
}
