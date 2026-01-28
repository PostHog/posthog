import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconMinusSquare, IconPlusSquare, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { logsSceneLogic } from '../../../../logsSceneLogic'
import { DateRangeFilter } from '../DateRangeFilter'
import { FilterHistoryDropdown } from '../FilterHistoryDropdown'
import { LogsDateRangePicker } from '../LogsDateRangePicker/LogsDateRangePicker'
import { ServiceFilter } from '../ServiceFilter'
import { SeverityLevelsFilter } from '../SeverityLevelsFilter'

const taxonomicFilterLogicKey = 'logs'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Logs,
    TaxonomicFilterGroupType.LogResourceAttributes,
    TaxonomicFilterGroupType.LogAttributes,
]

export const LogsFilterBar = (): JSX.Element => {
    const newLogsDateRangePicker = useFeatureFlag('NEW_LOGS_DATE_RANGE_PICKER')
    const { logsLoading, liveTailRunning, liveTailDisabledReason, dateRange } = useValues(logsSceneLogic)
    const { runQuery, zoomDateRange, setLiveTailRunning, setDateRange } = useActions(logsSceneLogic)

    return (
        <LogsFilterGroup>
            <div className="flex flex-col gap-2 w-full bg-primary">
                <div className="flex gap-2 flex-wrap w-full justify-between">
                    <div className="flex shrink-0 flex-1 gap-1.5">
                        <SeverityLevelsFilter />
                        <ServiceFilter />
                        <div className="min-w-[300px] max-w-[350px] w-full">
                            <LogsFilterSearch />
                        </div>
                        <FilterHistoryDropdown />
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                        <LemonButton
                            size="small"
                            icon={<IconMinusSquare />}
                            type="secondary"
                            onClick={() => zoomDateRange(2)}
                        />
                        <LemonButton
                            size="small"
                            icon={<IconPlusSquare />}
                            type="secondary"
                            onClick={() => zoomDateRange(0.5)}
                        />

                        {!newLogsDateRangePicker && <DateRangeFilter />}
                        {newLogsDateRangePicker && (
                            <LogsDateRangePicker dateRange={dateRange} setDateRange={setDateRange} />
                        )}

                        <LemonButton
                            size="small"
                            icon={<IconRefresh />}
                            type="secondary"
                            onClick={() => runQuery()}
                            loading={logsLoading || liveTailRunning}
                            disabledReason={liveTailRunning ? 'Disable live tail to manually refresh' : undefined}
                        />
                        <AppShortcut
                            name="LogsLiveTail"
                            keybind={[keyBinds.edit]}
                            intent={liveTailRunning ? 'Stop live tail' : 'Start live tail'}
                            interaction="click"
                            scope={Scene.Logs}
                        >
                            <LemonButton
                                size="small"
                                type={liveTailRunning ? 'primary' : 'secondary'}
                                icon={liveTailRunning ? <IconPauseCircle /> : <IconPlayCircle />}
                                onClick={() => setLiveTailRunning(!liveTailRunning)}
                                disabledReason={liveTailRunning ? undefined : liveTailDisabledReason}
                            >
                                Live tail
                            </LemonButton>
                        </AppShortcut>
                    </div>
                </div>
                <LogsAppliedFilters />
            </div>
        </LogsFilterGroup>
    )
}

const LogsFilterGroup = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { filterGroup, tabId, utcDateRange, serviceNames, filterGroup: logsFilterGroup } = useValues(logsSceneLogic)
    const { setFilterGroup } = useActions(logsSceneLogic)
    const { setFilter } = useActions(logsViewerConfigLogic)

    const endpointFilters = {
        dateRange: { ...utcDateRange, date_to: utcDateRange.date_to ?? dayjs().toISOString() },
        filterGroup: logsFilterGroup,
        serviceNames: serviceNames,
    }

    return (
        <UniversalFilters
            rootKey={`${taxonomicFilterLogicKey}-${tabId}`}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            endpointFilters={endpointFilters}
            onChange={(group) => {
                const newFilterGroup = { type: FilterLogicalOperator.And, values: [group] }
                setFilterGroup(newFilterGroup)
                setFilter('filterGroup', newFilterGroup)
            }}
        >
            {children}
        </UniversalFilters>
    )
}

const LogsFilterSearch = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { utcDateRange, serviceNames, filterGroup: logsFilterGroup } = useValues(logsSceneLogic)
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
            filterGroup: logsFilterGroup,
            serviceNames: serviceNames,
        },
        onChange: (taxonomicGroup, value, item, originalQuery) => {
            if (item.value === undefined) {
                addGroupFilter(taxonomicGroup, value, item, originalQuery)
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
                    docLink="https://posthog.com/docs/logs/search"
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

const LogsAppliedFilters = (): JSX.Element | null => {
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
