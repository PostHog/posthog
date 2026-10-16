import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { dateMapping, dateFilterToText } from 'lib/utils/dateFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { HogQLQuery, Node } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ItemMode, InsightShortId } from '~/types'

import { InsightFilterOverride } from 'products/product_analytics/frontend/insights/shared/InsightFilterOverride'

const FILTERS_PLACEHOLDER = /\{\s*filters\b/

function hogQLSource(query: Node | null): HogQLQuery | null {
    const source = isDataVisualizationNode(query) || isDataTableNode(query) ? query.source : query
    return isHogQLQuery(source) ? source : null
}

interface SqlInsightFiltersProps {
    query: Node | null
    setQuery: (query: Node) => void
    children: ReactNode
}

/**
 * Date range and property filters for SQL insights whose query uses the `{filters}` placeholder,
 * shown in view mode inside the classic insight card. Edits update the query's `filters` in local
 * state and re-run it — exactly how changing the date on any other saved insight works. The saved
 * insight only changes when the user saves.
 */
export function SqlInsightFilters({ query, setQuery, children }: SqlInsightFiltersProps): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps, hasOverrides, editingDisabledReason, dashboardFilterOverrides, dashboardDateOverride } =
        useValues(insightLogic)

    const source = hogQLSource(query)
    if (
        insightMode !== ItemMode.View ||
        !query ||
        !source ||
        (!FILTERS_PLACEHOLDER.test(source.query) && !hasOverrides)
    ) {
        return <>{children}</>
    }

    const savedDateLabel = dateFilterToText(
        source.filters?.dateRange?.date_from,
        source.filters?.dateRange?.date_to,
        'All time'
    )
    const appliedDateLabel = dashboardDateOverride
        ? dateFilterToText(dashboardDateOverride.dateFrom, dashboardDateOverride.dateTo, 'All time')
        : null

    const setSource = (newSource: HogQLQuery): void => {
        if (isDataVisualizationNode(query) || isDataTableNode(query)) {
            const nextQuery = { ...query, source: newSource }
            setQuery(nextQuery)
        } else {
            setQuery(newSource)
        }
    }

    return (
        <div
            className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary"
            data-attr="sql-insight-filters"
        >
            {/* Mirrors InsightDisplayConfig's markup so the header matches classic insights */}
            <div className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]">
                {hasOverrides && insightProps.dashboardItemId && (
                    <div className="flex basis-full flex-wrap items-center gap-2 text-sm">
                        <span>Dashboard filters apply to this view. Discard them to edit the saved insight.</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.insightView(
                                insightProps.dashboardItemId as InsightShortId,
                                insightProps.dashboardId
                            )}
                        >
                            Discard dashboard filters
                        </LemonButton>
                    </div>
                )}
                {FILTERS_PLACEHOLDER.test(source.query) && (
                    <div className="flex items-start gap-x-2 flex-wrap gap-y-2">
                        <InsightFilterOverride
                            source={dashboardDateOverride?.source}
                            savedValue={appliedDateLabel !== savedDateLabel ? savedDateLabel : null}
                        >
                            <DateFilter
                                disabledReason={editingDisabledReason}
                                showExplicitDateToggle
                                allowTimePrecision
                                allowFixedRangeWithTime
                                dateFrom={
                                    dashboardDateOverride
                                        ? dashboardDateOverride.dateFrom
                                        : (source.filters?.dateRange?.date_from ?? null)
                                }
                                dateTo={
                                    dashboardDateOverride
                                        ? dashboardDateOverride.dateTo
                                        : (source.filters?.dateRange?.date_to ?? null)
                                }
                                explicitDate={source.filters?.dateRange?.explicitDate ?? false}
                                onChange={(date_from, date_to, explicitDate) =>
                                    setSource({
                                        ...source,
                                        filters: { ...source.filters, dateRange: { date_from, date_to, explicitDate } },
                                    })
                                }
                                dateOptions={dateMapping}
                                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                                makeLabel={(key) => (
                                    <>
                                        <IconCalendar /> {key}
                                    </>
                                )}
                            />
                        </InsightFilterOverride>
                        <span className="flex items-center gap-x-2 text-sm">
                            {hasOverrides ? (
                                <PropertyFilters
                                    propertyFilters={
                                        Array.isArray(source.filters?.properties) ? source.filters.properties : []
                                    }
                                    pageKey="sql-insight-saved-filters"
                                    onChange={(): void => {}}
                                    editable={false}
                                    disabledReason={editingDisabledReason ?? undefined}
                                />
                            ) : (
                                <EventPropertyFilters query={source} setQuery={setSource} />
                            )}
                        </span>
                        {dashboardFilterOverrides.filterTestAccounts && (
                            <InsightFilterOverride
                                source={dashboardFilterOverrides.filterTestAccounts.source}
                                savedValue={
                                    dashboardFilterOverrides.filterTestAccounts.value !==
                                        !!source.filters?.filterTestAccounts &&
                                    (source.filters?.filterTestAccounts ? 'Excluded' : 'Included')
                                }
                            >
                                <LemonSelect
                                    size="small"
                                    value={dashboardFilterOverrides.filterTestAccounts.value}
                                    disabledReason={editingDisabledReason}
                                    options={[
                                        { value: true, label: 'Exclude internal and test users' },
                                        { value: false, label: 'Include internal and test users' },
                                    ]}
                                />
                            </InsightFilterOverride>
                        )}
                        {dashboardFilterOverrides.propertyGroups.map(({ properties, source: filterSource }) => (
                            <InsightFilterOverride key={filterSource} source={filterSource}>
                                <PropertyFilters
                                    propertyFilters={properties}
                                    pageKey={`sql-insight-${filterSource}-filters`}
                                    onChange={(): void => {}}
                                    editable={false}
                                    disabledReason={editingDisabledReason ?? undefined}
                                />
                            </InsightFilterOverride>
                        ))}
                    </div>
                )}
            </div>
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}
