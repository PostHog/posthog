import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { sampleDataStateLogic } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { SampleDataTag } from 'scenes/insights/EmptyStates/SampleDataTag'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { formatItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import type { RetentionQueryResponse } from '~/queries/schema/schema-general'

import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabExploreUrl } from './homeTabDefaultTiles'
import { homeTabChartInsightId, homeTabDataCollectionId } from './homeTabQueryKeys'
import { getHomeTabSampleData } from './homeTabSampleData'
import { getHomeTabRetentionSummary, type HomeTabRetentionStat } from './homeTabViewCharts'

interface HomeTabRetentionStatTileProps {
    stat: HomeTabRetentionStat
    selected: boolean
    onSelect: () => void
}

export function HomeTabRetentionStatTile({ stat, selected, onSelect }: HomeTabRetentionStatTileProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { shouldShowSampleData, sampleDataPending } = useValues(sampleDataStateLogic)
    const theme = useChartTheme()
    const sampleData = useMemo(
        () => (shouldShowSampleData ? getHomeTabSampleData(stat.table) : undefined),
        [shouldShowSampleData, stat.table]
    )
    // Same key as the cohort table's chart, so the tile reads the table's results and sends no query of its own.
    const chartKey = sampleData ? `${stat.table.key}.sample` : stat.table.key
    const logic = dataNodeLogic({
        query: stat.table.query.source,
        key: insightVizDataNodeKey({ dashboardItemId: homeTabChartInsightId(currentTeamId, chartKey) }),
        cachedResults: sampleData,
        doNotLoad: sampleDataPending,
        loadPriority: 0,
        dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
    })
    useAttachedLogic(logic, homeTabDefaultLogic)
    const { response, responseLoading, responseError } = useValues(logic)
    const summary = getHomeTabRetentionSummary(
        (response as RetentionQueryResponse | null)?.results,
        stat.interval,
        stat.period
    )

    return (
        <AnalyticsMetricCard
            className="h-full w-full"
            header={
                <CardMeta
                    compact
                    showEditingControls
                    moreButtons={
                        <LemonButton
                            to={getHomeTabExploreUrl(stat.table.query)}
                            fullWidth
                            data-attr={`home-tab-stat-explore-${stat.key}`}
                        >
                            Explore
                        </LemonButton>
                    }
                    content={
                        <Tooltip title={stat.description}>
                            <span>
                                <InsightMetaContent title={stat.title} compact showDescription={false} />
                            </span>
                        </Tooltip>
                    }
                />
            }
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
            loading={responseLoading || sampleDataPending || (!response && !responseError)}
            error={responseError ? 'Could not load' : undefined}
            emptyMessage="No cohort has had the full time to come back yet"
            dataAttr={`home-tab-metric-${stat.key}`}
            value={summary?.value}
            showChange={false}
            data={summary?.trend}
            labels={summary?.labels}
            theme={theme}
            sparklineHeight={50}
            formatLabel={(date) => dayjs(date).format('MMM D')}
            goodDirection="up"
            formatValue={(value) => formatItem(value, 'percentage')}
            restingSubtitle={<span translate="no">Average of complete cohorts</span>}
        />
    )
}
