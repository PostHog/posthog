import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { heatmapDataLogic, selectedEventFilters } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapEventFilter } from 'lib/components/heatmaps/types'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover'
import { COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { AnyPropertyFilter, CohortPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { ViewportChooser } from './ViewportChooser'

const cohortIdsToPropertyFilters = (ids: number[]): AnyPropertyFilter[] =>
    ids.map((id) => ({
        type: PropertyFilterType.Cohort,
        key: 'id',
        value: id,
        operator: PropertyOperator.In,
    }))

const propertyFiltersToCohortIds = (filters: AnyPropertyFilter[]): number[] =>
    filters
        .filter((f): f is CohortPropertyFilter => f.type === PropertyFilterType.Cohort)
        .map((f) => f.value)
        .filter((v): v is number => typeof v === 'number')

export function HeatmapFilterControls({
    lockedWidth,
    settings,
    actions,
    drawerFooter,
}: {
    lockedWidth?: number
    settings?: ReactNode
    actions?: ReactNode
    drawerFooter?: ReactNode
}): JSX.Element {
    const [filtersOpen, setFiltersOpen] = useState(false)
    const [isEventFilterOpen, setIsEventFilterOpen] = useState(false)
    const { commonFilters } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { setCommonFilters } = useActions(heatmapDataLogic({ context: 'in-app' }))

    const cohortFilterEnabled = useFeatureFlag('HEATMAPS_COHORT_FILTER')
    const eventFilterEnabled = useFeatureFlag('HEATMAPS_EVENT_FILTER')
    const eventFilterCount = selectedEventFilters(commonFilters?.events).length
    const filterCount =
        (commonFilters?.cohort_ids?.length ?? 0) + eventFilterCount + Number(!!commonFilters?.filter_test_accounts)

    return (
        <div className="@container/heatmap-filters">
            <div className="flex flex-wrap items-center gap-2 my-2">
                <div className="basis-full @min-[40rem]/heatmap-filters:basis-auto min-w-0">
                    <DateFilter
                        dateFrom={commonFilters?.date_from}
                        dateTo={commonFilters?.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters?.({ ...commonFilters, date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
                    />
                </div>
                <ViewportChooser lockedWidth={lockedWidth} />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconFilter />}
                    sideIcon={filterCount ? <LemonBadge.Number count={filterCount} size="small" /> : undefined}
                    active={filtersOpen}
                    aria-expanded={filtersOpen}
                    onClick={() => setFiltersOpen(!filtersOpen)}
                    data-attr="heatmap-filters-toggle"
                >
                    Filters
                </LemonButton>
                {settings}
                {actions && <div className="ml-auto">{actions}</div>}
            </div>
            <div className={filtersOpen ? 'flex flex-wrap items-center gap-3 mb-2' : 'hidden'}>
                {cohortFilterEnabled && (
                    <div className="min-w-0">
                        <PropertyFilters
                            pageKey="heatmap-cohorts"
                            propertyFilters={cohortIdsToPropertyFilters(commonFilters?.cohort_ids ?? [])}
                            onChange={(filters) =>
                                setCommonFilters?.({
                                    ...commonFilters,
                                    cohort_ids: propertyFiltersToCohortIds(filters),
                                })
                            }
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                            buttonText="Filter by cohort"
                            addText="Add cohort filter"
                            buttonSize="small"
                            {...COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS}
                        />
                    </div>
                )}
                {eventFilterEnabled && (
                    <div className="min-w-0">
                        <Popover
                            overlay={
                                // The filter bar is a single row of controls, so the event list, which grows a
                                // row per event, sits in a popover rather than stretching the row it lives in.
                                <div className="p-2 w-96">
                                    <ActionFilter
                                        bordered
                                        filters={{ events: commonFilters?.events ?? [] }}
                                        setFilters={(filters) => {
                                            setCommonFilters?.({
                                                ...commonFilters,
                                                // ActionFilter types events as the loose Record shape; narrow
                                                // back to what heatmapDataLogic serializes.
                                                events: (filters.events ?? []) as HeatmapEventFilter[],
                                            })
                                        }}
                                        typeKey="heatmap-events"
                                        buttonCopy="Add event"
                                        mathAvailability={MathAvailability.None}
                                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                                        // "All events" matches every session, so as a filter it does nothing.
                                        excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null] }}
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                        ]}
                                        propertyFiltersPopover
                                        hideRename
                                        hideDuplicate
                                        showNestedArrow={false}
                                    />
                                </div>
                            }
                            visible={isEventFilterOpen}
                            onClickOutside={() => setIsEventFilterOpen(false)}
                            placement="bottom"
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconFilter />}
                                sideIcon={
                                    eventFilterCount ? (
                                        <LemonBadge.Number count={eventFilterCount} size="small" />
                                    ) : undefined
                                }
                                onClick={() => setIsEventFilterOpen(!isEventFilterOpen)}
                                tooltip="Only show interactions from sessions where these events happened"
                                data-attr="heatmap-event-filter"
                            >
                                Filter by event
                            </LemonButton>
                        </Popover>
                    </div>
                )}
                <div className="min-w-0">
                    <TestAccountFilter
                        size="small"
                        filters={{ filter_test_accounts: commonFilters?.filter_test_accounts }}
                        onChange={(value) => {
                            setCommonFilters?.({
                                ...commonFilters,
                                filter_test_accounts: value.filter_test_accounts,
                            })
                        }}
                    />
                </div>
                {drawerFooter}
            </div>
        </div>
    )
}
