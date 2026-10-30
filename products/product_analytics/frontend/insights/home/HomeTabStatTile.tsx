import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { CompactInfoPopover } from 'lib/components/Cards/InsightCard/CompactInfoPopover'
import { InsightDetails } from 'lib/components/Cards/InsightCard/InsightDetails'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
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
import {
    getHomeTabExploreUrl,
    getHomeTabStatInsightQuery,
    getHomeTabStatValue,
    isHomeTabStatBucketInProgress,
    type HomeTabStatQuery,
} from './homeTabDefaultTiles'
import { homeTabDataCollectionId, homeTabStatKey, homeTabStatTrendKey } from './homeTabQueryKeys'
import { getHomeTabSampleStatData } from './homeTabSampleData'

const SESSION_DURATION_DESCRIPTION = 'Average duration of sessions with a page or screen view.'

interface HomeTabStatTileProps {
    stat: HomeTabStatQuery
    compare: boolean
    selected: boolean
    onSelect: () => void
}

export function HomeTabStatTile({ stat, compare, selected, onSelect }: HomeTabStatTileProps): JSX.Element {
    const { currentTeamId, currentTeam } = useValues(teamLogic)
    const { shouldShowSampleData, sampleDataPending } = useValues(sampleDataStateLogic)
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
    const keySuffix = shouldShowSampleData ? '.sample' : sampleDataPending ? '.pending' : ''
    const key = homeTabStatKey(currentTeamId, stat.key)
    const logic = dataNodeLogic({
        query: stat.query,
        loadPriority: 0,
        key: `${key}${keySuffix}`,
        cachedResults: sampleData,
        doNotLoad: shouldShowSampleData || sampleDataPending,
        dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
    })
    useAttachedLogic(logic, homeTabDefaultLogic)
    const trendLogic = dataNodeLogic({
        query: stat.trendQuery ?? stat.query,
        loadPriority: stat.trendQuery && !stat.trendKey ? 1 : 0,
        key: `${homeTabStatTrendKey(currentTeamId, stat)}${keySuffix}`,
        cachedResults: sampleTrendData,
        doNotLoad: shouldShowSampleData || sampleDataPending,
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
    const { response, responseError, responseLoading, lastRefresh } = useValues(logic)
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

    const insightQuery = getHomeTabStatInsightQuery(stat)
    const description = stat.description ?? (stat.key === 'session_duration' ? SESSION_DURATION_DESCRIPTION : null)
    const header = (
        <CardMeta
            compact
            showEditingControls
            moreButtons={
                <LemonButton
                    to={getHomeTabExploreUrl(insightQuery)}
                    fullWidth
                    data-attr={`home-tab-stat-explore-${stat.key}`}
                >
                    Explore
                </LemonButton>
            }
            content={
                <InsightMetaContent
                    title={stat.title}
                    compact
                    showDescription={false}
                    infoPopover={
                        <CompactInfoPopover
                            popoverTopHeading={
                                <TopHeading
                                    query={insightQuery}
                                    lastRefresh={shouldShowSampleData ? null : lastRefresh}
                                    resolvedDateRange={(response as TrendsQueryResponse | null)?.resolved_date_range}
                                />
                            }
                            metaTitle={stat.title}
                            metaDescription={
                                description ? (
                                    <LemonMarkdown className="text-xs" lowKeyHeadings>
                                        {description}
                                    </LemonMarkdown>
                                ) : null
                            }
                            metaDescriptionText={description ?? ''}
                            metaDetails={<InsightDetails query={insightQuery} />}
                        />
                    }
                />
            }
        />
    )

    const subtitle = !compare
        ? 'For selected period'
        : previousValue == null
          ? 'No previous period data'
          : `vs. ${formatItem(previousValue, stat.kind)} prior`

    return (
        <AnalyticsMetricCard
            className="h-full w-full"
            header={header}
            adornment={
                shouldShowSampleData ? (
                    <div className="flex justify-end px-3 pb-3">
                        <SampleDataTag />
                    </div>
                ) : undefined
            }
            title={null}
            ariaLabel={stat.title}
            onClick={onSelect}
            selected={selected}
            loading={loading}
            error={responseError ? 'Could not load' : undefined}
            dataAttr={`home-tab-metric-${stat.key}`}
            value={value ?? undefined}
            showChange={compare}
            change={changeFromPreviousPct != null ? { value: changeFromPreviousPct } : null}
            changeBesideSubtitle
            hoverChangeFromPreviousPoint
            data={trend?.data}
            labels={trend?.days}
            theme={theme}
            sparklineHeight={50}
            sparklineDashedFromIndex={incompleteTail ? (trend?.data.length ?? 0) - 1 : undefined}
            formatLabel={(bucket) => formatBucketLabel(bucket, interval)}
            goodDirection="up"
            formatValue={(statValue) => formatItem(statValue, stat.kind)}
            restingSubtitle={<span translate="no">{subtitle}</span>}
        />
    )
}
