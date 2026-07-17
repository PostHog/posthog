import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

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
    const { filterGroup, serviceNames } = filters
    const { setFilterGroup } = useActions(logsViewerFiltersLogic)

    // Taxonomic value suggestions should respect any active scope (e.g. the person-tab
    // distinct_id pin), so pass the combined query view rather than the user-editable
    // filterGroup. The UniversalFilters `group` prop stays on the editable filterGroup
    // so chips reflect what the user can actually edit.
    const endpointFilters = {
        dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
        filterGroup: queryFilterGroup,
        serviceNames,
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

export const LogsFilterSearch = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { utcDateRange, filters: logsFilters, queryFilterGroup } = useValues(logsViewerFiltersLogic)
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
            serviceNames: logsFilters.serviceNames,
        },
        onChange: (taxonomicGroup, value, item) => {
            if (item.value === undefined) {
                addGroupFilter(taxonomicGroup, value, item)
                setVisible(false)
                return
            }

            const newValues = [...filterGroup.values]
            const newPropertyFilter = {
                key: item.key,
                value: item.value,
                operator: PropertyOperator.IContains,
                type: item.propertyFilterType,
            } as AnyPropertyFilter
            newValues.push(newPropertyFilter)
            setGroupValues(newValues)
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
