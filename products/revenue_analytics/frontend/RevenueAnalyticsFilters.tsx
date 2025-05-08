import { IconFilter, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { DATE_FORMAT, formatDateRange } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'
import { DateMappingOption, ExternalDataSource } from '~/types'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

const DATE_FILTER_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Month to date',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('d').format(DATE_FORMAT),
        defaultInterval: 'day',
    },
    {
        key: 'Last month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('y')),
        defaultInterval: 'month',
    },
    {
        key: 'Previous year',
        values: ['-1yStart', '-1yEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'year').startOf('y'), date.subtract(1, 'year').endOf('y')),
        defaultInterval: 'month',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

type ParsedRecord = Record<string, boolean>
const buildEvents = (allEvents: RevenueAnalyticsEventItem[], state: ParsedRecord): ParsedRecord => {
    return allEvents.reduce((acc, event) => {
        if (!(event.eventName in acc)) {
            acc[event.eventName] = true
        }
        return acc
    }, state)
}

const buildDataWarehouseSources = (
    allDataWarehouseSources: ExternalDataSource[],
    state: ParsedRecord
): ParsedRecord => {
    return allDataWarehouseSources
        .filter((source) => source.revenue_analytics_enabled)
        .reduce((acc, source) => {
            if (!(source.id in acc)) {
                acc[source.id] = true
            }
            return acc
        }, state)
}

export const RevenueAnalyticsFilters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
    } = useValues(revenueAnalyticsLogic)
    const { setDates } = useActions(revenueAnalyticsLogic)

    return (
        <div className="flex flex-row w-full justify-between gap-1">
            <div className="flex flex-row gap-1">
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={setDates}
                    dateOptions={DATE_FILTER_DATE_OPTIONS}
                />

                <Tooltip title="Refresh data">
                    <ReloadAll iconOnly />
                </Tooltip>
            </div>

            <RevenueAnalyticsFiltersModal />
        </div>
    )
}

const RevenueAnalyticsFiltersModal = (): JSX.Element => {
    const { allEvents, allDataWarehouseSources } = useValues(revenueAnalyticsLogic)
    const { setRevenueSources } = useActions(revenueAnalyticsLogic)

    const [events, setEvents] = useState(() => buildEvents(allEvents, {}))
    const [dataWarehouseSources, setDataWarehouseSources] = useState(() =>
        buildDataWarehouseSources(allDataWarehouseSources?.results ?? [], {})
    )

    // When the revenue sources change, we need to update the events and data warehouse sources
    useEffect(() => {
        setEvents((events) => buildEvents(allEvents, events))
        setDataWarehouseSources((dataWarehouseSources) =>
            buildDataWarehouseSources(allDataWarehouseSources?.results ?? [], dataWarehouseSources)
        )
    }, [allEvents, allDataWarehouseSources])

    // The modal below insists in keeping references to the old values because of the way `Overlay` works.
    // So we need to keep our own references to the values and update them on every render.
    const eventsRef = useRef(events)
    useEffect(() => {
        eventsRef.current = events
    }, [events])
    const dataWarehouseSourcesRef = useRef(dataWarehouseSources)
    useEffect(() => {
        dataWarehouseSourcesRef.current = dataWarehouseSources
    }, [dataWarehouseSources])

    const updateEvent = (eventName: string, enabled: boolean): void => {
        setEvents((events) => ({ ...events, [eventName]: enabled }))
    }

    const updateDataWarehouseSource = (sourceId: string, enabled: boolean): void => {
        setDataWarehouseSources((dataWarehouseSources) => ({ ...dataWarehouseSources, [sourceId]: enabled }))
    }

    const areAllEventsEnabled = Object.values(events).every((enabled) => enabled)
    const areAllEventsDisabled = Object.values(events).length > 0 && Object.values(events).every((enabled) => !enabled)
    const areAllDataWarehouseSourcesEnabled = Object.values(dataWarehouseSources).every((enabled) => enabled)
    const areAllDataWarehouseSourcesDisabled =
        Object.values(dataWarehouseSources).length > 0 &&
        Object.values(dataWarehouseSources).every((enabled) => !enabled)
    const areAllEnabled = areAllEventsEnabled && areAllDataWarehouseSourcesEnabled
    const areAllDisabled = areAllEventsDisabled || areAllDataWarehouseSourcesDisabled

    return (
        <LemonDropdown
            closeOnClickInside={false}
            onVisibilityChange={(visible): void => {
                if (visible) {
                    return
                }

                const selectedEvents = allEvents.filter((event) => eventsRef.current[event.eventName])
                const selectedDataWarehouseSources =
                    allDataWarehouseSources?.results.filter((source) => dataWarehouseSourcesRef.current[source.id]) ??
                    []
                setRevenueSources({ events: selectedEvents, dataWarehouseSources: selectedDataWarehouseSources })
            }}
            overlay={
                <div className="flex flex-col sm:flex-row justify-between sm:min-w-[400px] p-2 gap-5">
                    <div>
                        <span className="text-sm font-medium pb-2">
                            Events
                            <Link className="ml-1" to={urls.revenueSettings()}>
                                <IconPlus />
                            </Link>
                        </span>
                        <div className="flex flex-col gap-1">
                            {allEvents.map((event) => (
                                <div className="flex flex-row gap-1" key={event.eventName}>
                                    <LemonSwitch
                                        checked={events[event.eventName]}
                                        onChange={(checked) => updateEvent(event.eventName, checked)}
                                    />
                                    {event.eventName}
                                </div>
                            ))}

                            {allEvents.length === 0 && (
                                <>
                                    <span className="text-sm text-muted-alt">No revenue events found</span>
                                </>
                            )}
                        </div>
                    </div>
                    <div>
                        <span className="text-sm font-medium pb-2">
                            Data warehouse sources
                            <Link className="ml-1" to={urls.revenueSettings()}>
                                <IconPlus />
                            </Link>
                        </span>
                        <div className="flex flex-col gap-1">
                            {allDataWarehouseSources?.results.map((source) => (
                                <div className="flex flex-row gap-1" key={source.id}>
                                    <LemonSwitch
                                        checked={dataWarehouseSources[source.id]}
                                        onChange={(checked) => updateDataWarehouseSource(source.id, checked)}
                                    />
                                    <span className="ml-1">{source.prefix || source.source_type}</span>
                                    <DataWarehouseSourceIcon type={source.source_type} size="xsmall" />
                                </div>
                            ))}

                            {!allDataWarehouseSources?.results.length && (
                                <>
                                    <span className="text-sm text-muted-alt">
                                        No enabled revenue data warehouse sources found
                                    </span>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                tooltip="Choose which revenue sources should be taken into consideration"
                icon={
                    <IconWithBadge
                        content={areAllDisabled ? '!' : !areAllEnabled ? '*' : undefined}
                        status={areAllDisabled ? 'danger' : 'data'}
                    >
                        <IconFilter />
                    </IconWithBadge>
                }
            />
        </LemonDropdown>
    )
}
