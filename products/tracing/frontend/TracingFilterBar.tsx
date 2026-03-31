import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronDown, IconMinusSquare, IconPlusSquare, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils'

import { DateRange } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    DateMappingOption,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingServiceFilterLogic, TracingServiceFilterLogicProps } from './tracingServiceFilterLogic'

const taxonomicFilterLogicKey = 'tracing'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Spans,
    TaxonomicFilterGroupType.SpanAttributes,
    TaxonomicFilterGroupType.SpanResourceAttributes,
]

const dateMapping: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 4 hours',
        values: ['-4h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(4, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

export function TracingFilterBar(): JSX.Element {
    const { spansLoading } = useValues(tracingDataLogic)
    const { runQuery } = useActions(tracingDataLogic)
    const { filters, utcDateRange } = useValues(tracingFiltersLogic)
    const { setDateRange, setServiceNames, setFilterGroup } = useActions(tracingFiltersLogic)
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
                        <div className="flex">
                            <LemonButton
                                size="small"
                                icon={<IconMinusSquare />}
                                type="secondary"
                                tooltip="Zoom out"
                                onClick={() => {
                                    const from = dayjs(dateRange.date_from)
                                    const to = dateRange.date_to ? dayjs(dateRange.date_to) : dayjs()
                                    const diff = to.diff(from, 'millisecond')
                                    setDateRange({
                                        date_from: from.subtract(diff / 2, 'millisecond').toISOString(),
                                        date_to: to.add(diff / 2, 'millisecond').toISOString(),
                                    })
                                }}
                            />
                            <DateFilter
                                size="small"
                                dateFrom={dateRange.date_from}
                                dateTo={dateRange.date_to}
                                dateOptions={dateMapping}
                                onChange={(changedDateFrom, changedDateTo) => {
                                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                                }}
                                allowTimePrecision
                                allowFixedRangeWithTime
                                allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks', 'months']}
                                use24HourFormat
                            />
                            <LemonButton
                                size="small"
                                icon={<IconPlusSquare />}
                                type="secondary"
                                tooltip="Zoom in"
                                onClick={() => {
                                    const from = dayjs(dateRange.date_from)
                                    const to = dateRange.date_to ? dayjs(dateRange.date_to) : dayjs()
                                    const diff = to.diff(from, 'millisecond')
                                    setDateRange({
                                        date_from: from.add(diff / 4, 'millisecond').toISOString(),
                                        date_to: to.subtract(diff / 4, 'millisecond').toISOString(),
                                    })
                                }}
                            />
                        </div>
                        <LemonButton
                            size="small"
                            icon={<IconRefresh />}
                            type="secondary"
                            onClick={() => runQuery()}
                            loading={spansLoading}
                        />
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
    const { utcDateRange, filters } = useValues(tracingFiltersLogic)

    const endpointFilters = {
        dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
        filterGroup,
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
    const { utcDateRange, filters: tracingFilters } = useValues(tracingFiltersLogic)
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
            filterGroup: tracingFilters.filterGroup,
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
                            useVerticalLayout={true}
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

interface TracingServiceFilterProps {
    value: string[]
    onChange: (serviceNames: string[]) => void
    dateRange?: DateRange
}

function TracingServiceFilter({ value, onChange, dateRange }: TracingServiceFilterProps): JSX.Element {
    const logicProps: TracingServiceFilterLogicProps = { dateRange }

    return (
        <BindLogic logic={tracingServiceFilterLogic} props={logicProps}>
            <TracingServiceFilterInner value={value} onChange={onChange} />
        </BindLogic>
    )
}

function TracingServiceFilterInner({
    value,
    onChange,
}: {
    value: string[]
    onChange: (serviceNames: string[]) => void
}): JSX.Element {
    const { serviceNames, allServiceNames, allServiceNamesLoading, search } = useValues(tracingServiceFilterLogic)
    const { setSearch } = useActions(tracingServiceFilterLogic)

    const selected = value ?? []

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1">
                    <div className="px-1 pb-1">
                        <LemonInput
                            type="search"
                            placeholder="Search services..."
                            size="small"
                            fullWidth
                            value={search}
                            onChange={(val) => setSearch(val)}
                            autoFocus
                        />
                    </div>
                    <div className="max-h-[300px] overflow-y-auto">
                        {allServiceNamesLoading && allServiceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">Loading...</div>
                        ) : serviceNames.length === 0 ? (
                            <div className="p-2 text-muted text-center text-xs">
                                {search ? 'No matching services' : 'No services found'}
                            </div>
                        ) : (
                            <>
                                {selected.length > 0 && (
                                    <>
                                        <div className="flex flex-wrap gap-1 px-1 pb-1 max-w-[300px]">
                                            {selected.map((name: string) => (
                                                <LemonTag
                                                    key={`selected-${name}`}
                                                    type="highlight"
                                                    closable
                                                    size="small"
                                                    onClose={() => onChange(selected.filter((n) => n !== name))}
                                                >
                                                    {name}
                                                </LemonTag>
                                            ))}
                                        </div>
                                        <div className="border-b border-border my-1" />
                                    </>
                                )}
                                {serviceNames.map((name: string) => {
                                    const isSelected = selected.includes(name)
                                    return (
                                        <LemonButton
                                            key={name}
                                            type="tertiary"
                                            size="small"
                                            fullWidth
                                            icon={
                                                <LemonCheckbox checked={isSelected} className="pointer-events-none" />
                                            }
                                            onClick={() => {
                                                const newNames = isSelected
                                                    ? selected.filter((n) => n !== name)
                                                    : [...selected, name]
                                                onChange(newNames)
                                            }}
                                        >
                                            {name}
                                        </LemonButton>
                                    )
                                })}
                            </>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                data-attr="tracing-service-filter"
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                loading={allServiceNamesLoading && selected.length === 0}
            >
                {selected.length === 0
                    ? 'All services'
                    : selected.length === 1
                      ? selected[0]
                      : `${selected.length} services`}
            </LemonButton>
        </LemonDropdown>
    )
}
