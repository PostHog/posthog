import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { formatBucketLabel } from 'lib/utils/timeBuckets'
import { sampleDataStateLogic } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { SampleDataTag } from 'scenes/insights/EmptyStates/SampleDataTag'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { formatItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import type { TrendsQueryResponse } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabStatValue, isHomeTabStatBucketInProgress, type HomeTabStatQuery } from './homeTabDefaultTiles'
import { homeTabDataCollectionId, homeTabStatKey, homeTabStatTrendKey } from './homeTabQueryKeys'
import { getHomeTabSampleStatData } from './homeTabSampleData'

interface HomeTabStatTileProps {
    stat: HomeTabStatQuery
    compare: boolean
    selected: boolean
    onSelect: () => void
}

export function HomeTabStatTile({ stat, compare, selected, onSelect }: HomeTabStatTileProps): JSX.Element {
    const { currentTeamId, currentTeam } = useValues(teamLogic)
    const { shouldShowSampleData } = useValues(sampleDataStateLogic)
    const sampleData = useMemo(
        () => (shouldShowSampleData ? getHomeTabSampleStatData(stat.key, stat.query) : undefined),
        [shouldShowSampleData, stat.key, stat.query]
    )
    const sampleTrendData = useMemo(
        () =>
            shouldShowSampleData
                ? getHomeTabSampleStatData(stat.trendKey ?? stat.key, stat.trendQuery ?? stat.query)
                : undefined,
        [shouldShowSampleData, stat.key, stat.trendKey, stat.trendQuery, stat.query]
    )
    const theme = useChartTheme()
    const key = homeTabStatKey(currentTeamId, stat.key)
    const logic = dataNodeLogic({
        query: stat.query,
        loadPriority: 0,
        key: shouldShowSampleData ? `${key}.sample` : key,
        cachedResults: sampleData,
        doNotLoad: shouldShowSampleData,
        dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
    })
    useAttachedLogic(logic, homeTabDefaultLogic)
    const trendLogic = dataNodeLogic({
        query: stat.trendQuery ?? stat.query,
        loadPriority: stat.trendQuery && !stat.trendKey ? 1 : 0,
        key: `${homeTabStatTrendKey(currentTeamId, stat)}${shouldShowSampleData ? '.sample' : ''}`,
        cachedResults: sampleTrendData,
        doNotLoad: shouldShowSampleData,
        dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
    })
    useAttachedLogic(trendLogic, homeTabDefaultLogic)
    const { response: trendResponse, responseLoading: trendLoading, responseError: trendError } = useValues(trendLogic)
    const trend =
        trendLoading || trendError
            ? undefined
            : ((trendResponse as TrendsQueryResponse | undefined)?.results?.[0] as TrendResult | undefined)
    const interval = (stat.trendQuery ?? stat.query).interval ?? 'day'
    const incompleteTail = isHomeTabStatBucketInProgress(
        trend,
        interval,
        currentTeam?.timezone ?? 'UTC',
        currentTeam?.week_start_day
    )
    const { response, responseError, responseLoading } = useValues(logic)
    const loading = responseLoading || (!response && !responseError)

    const results = (response as TrendsQueryResponse | undefined)?.results ?? (response as { result?: unknown })?.result
    const current = (results as TrendResult[] | undefined)?.[0]
    const previous = compare ? (results as TrendResult[] | undefined)?.[1] : undefined
    const value = getHomeTabStatValue(stat, current)
    const previousValue = getHomeTabStatValue(stat, previous)
    const changeFromPreviousPct =
        value != null && previousValue != null && previousValue !== 0
            ? ((value - previousValue) / Math.abs(previousValue)) * 100
            : undefined

    const label =
        stat.description || stat.key === 'session_duration' ? (
            <Tooltip title={stat.description ?? 'Average duration of sessions with a page or screen view.'}>
                {stat.title}
            </Tooltip>
        ) : (
            stat.title
        )

    const subtitle = !compare
        ? 'For selected period'
        : previousValue == null
          ? 'No previous period data'
          : `vs. ${formatItem(previousValue, stat.kind)} prior`

    return (
        <AnalyticsMetricCard
            className="h-full w-full"
            adornment={
                shouldShowSampleData ? (
                    <div className="flex justify-end px-3 pb-3">
                        <SampleDataTag />
                    </div>
                ) : undefined
            }
            title={label}
            ariaLabel={stat.title}
            onClick={onSelect}
            selected={selected}
            loading={loading}
            error={responseError ? 'Could not load' : undefined}
            dataAttr={`home-tab-metric-${stat.key}`}
            value={value ?? undefined}
            showChange={compare}
            change={changeFromPreviousPct != null ? { value: changeFromPreviousPct } : null}
            hoverChangeFromPreviousPoint
            data={trend?.data}
            labels={trend?.days}
            theme={theme}
            sparklineHeight={50}
            sparklineClassName="mt-3"
            sparklineDashedFromIndex={incompleteTail ? (trend?.data.length ?? 0) - 1 : undefined}
            formatLabel={(bucket) => formatBucketLabel(bucket, interval)}
            goodDirection="up"
            formatValue={(statValue) => formatItem(statValue, stat.kind)}
            restingSubtitle={<span translate="no">{subtitle}</span>}
        />
    )
}
