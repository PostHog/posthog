import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { DateRangePickerWithZoom } from 'lib/components/DateFilter/DateRangePicker'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { DateRange } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { TracingServiceFilter } from './components/TracingServiceFilter'
import { SavedViewsButton } from './savedViews/SavedViewsButton'
import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'

const taxonomicFilterLogicKey = 'tracing'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Spans,
    TaxonomicFilterGroupType.SpanAttributes,
    TaxonomicFilterGroupType.SpanResourceAttributes,
]

export function TracingFilterBar(): JSX.Element {
    const { spansLoading } = useValues(tracingDataLogic)
    const { refreshQuery } = useActions(tracingDataLogic)
    const { filters, utcDateRange, timezone } = useValues(tracingFiltersLogic)
    const { setDateRange, setTimezone, setServiceNames, setFilterGroup } = useActions(tracingFiltersLogic)
    const { dateRange, serviceNames, filterGroup } = filters

    return (
        <TracingFilterGroup filterGroup={filterGroup} onFilterGroupChange={setFilterGroup}>
            <div className="flex flex-col gap-2 w-full">
                <div className="flex gap-2 flex-wrap w-full justify-between">
                    <div className="flex shrink-0 flex-1 gap-1.5">
                        <TracingServiceFilter
                            value={serviceNames}
                            onChange={setServiceNames}
                            dateRange={utcDateRange as DateRange}
                        />
                        <div className="min-w-[200px] max-w-[300px] w-full">
                            <TracingFilterSearch />
                        </div>
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                        <DateRangePickerWithZoom
                            logicKey="tracing"
                            dateRange={dateRange}
                            setDateRange={setDateRange}
                            timezone={timezone}
                            onTimezoneChange={setTimezone}
                        />
                        <LemonButton
                            size="small"
                            icon={<IconRefresh />}
                            type="secondary"
                            onClick={() => refreshQuery()}
                            loading={spansLoading}
                        />
                        <SavedViewsButton />
                    </div>
                </div>
                <TracingAppliedFilters />
            </div>
        </TracingFilterGroup>
    )
}

function TracingFilterGroup({
    filterGroup,
    onFilterGroupChange,
    children,
}: {
    filterGroup: UniversalFiltersGroup
    onFilterGroupChange: (filterGroup: UniversalFiltersGroup) => void
    children: React.ReactNode
}): JSX.Element {
    const { utcDateRange, filters, queryFilterGroup } = useValues(tracingFiltersLogic)

    // Suggestions are scoped by the query-facing group (pinned filters included) so an
    // embedded viewer only suggests values that exist within its pinned scope.
    const endpointFilters = {
        dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
        filterGroup: queryFilterGroup,
        serviceNames: filters.serviceNames,
    }

    return (
        <UniversalFilters
            rootKey={taxonomicFilterLogicKey}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            endpointFilters={endpointFilters}
            onChange={(group) => {
                onFilterGroupChange({ type: FilterLogicalOperator.And, values: [group] })
            }}
        >
            {children}
        </UniversalFilters>
    )
}

function TracingFilterSearch(): JSX.Element {
    const [visible, setVisible] = useState<boolean>(false)
    const { utcDateRange, filters: tracingFilters, queryFilterGroup } = useValues(tracingFiltersLogic)
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
            serviceNames: tracingFilters.serviceNames,
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
                    size="small"
                    fullWidth
                />
            </LemonDropdown>
        </BindLogic>
    )
}

function FilterGroupValues({ allowInitiallyOpen }: { allowInitiallyOpen: boolean }): JSX.Element | null {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { suppressAutoOpenFilter } = useValues(tracingFiltersLogic)
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
                        initiallyOpen={
                            allowInitiallyOpen &&
                            filterOrGroup.type != PropertyFilterType.HogQL &&
                            filterOrGroup !== suppressAutoOpenFilter
                        }
                    />
                )
            })}
        </>
    )
}

function TracingAppliedFilters(): JSX.Element | null {
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
