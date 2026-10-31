import './HomeTabChartCard.scss'

import { useValues } from 'kea'
import { useMemo, type ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { sampleDataStateLogic } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { SampleDataTag } from 'scenes/insights/EmptyStates/SampleDataTag'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'

import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabExploreUrl, type HomeTabChartOption } from './homeTabDefaultTiles'
import { homeTabChartInsightId, homeTabDataCollectionId } from './homeTabQueryKeys'
import { getHomeTabSampleData } from './homeTabSampleData'

interface HomeTabChartCardProps {
    option: HomeTabChartOption
    size: 'primary' | 'supporting' | 'ranking'
    control?: ReactNode
    source?: string
    loadPriority: number
}

export function HomeTabChartCard({ option, size, control, source, loadPriority }: HomeTabChartCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { shouldShowSampleData, sampleDataPending } = useValues(sampleDataStateLogic)
    const sampleData = useMemo(
        () => (shouldShowSampleData ? getHomeTabSampleData(option) : undefined),
        [shouldShowSampleData, option]
    )
    const chartKey = sampleData ? `${option.key}.sample` : option.key
    const chart = sampleDataPending ? (
        <LemonSkeleton className="h-full w-full" />
    ) : (
        <Query
            key={`${currentTeamId}.${chartKey}`}
            query={option.query}
            readOnly
            inSharedMode={!!sampleData}
            cachedResults={sampleData}
            uniqueKey={`HomeTab.${currentTeamId}.${chartKey}`}
            context={{
                insightProps: {
                    loadPriority,
                    dashboardItemId: homeTabChartInsightId(currentTeamId, chartKey),
                    dataNodeCollectionId: homeTabDataCollectionId(currentTeamId),
                    query: option.query,
                },
            }}
            attachTo={homeTabDefaultLogic}
        />
    )
    return (
        <LemonCard hoverEffect={false} className="HomeTabChartCard flex min-w-0 flex-col overflow-hidden p-0">
            <div className="HomeTabChartCard__header border-b border-primary px-4 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <div className="flex min-w-0 items-center gap-1">
                        <h3 className="m-0 truncate text-base font-semibold">{option.title}</h3>
                        {source && (
                            <Tooltip title={`Based on ${source}`}>
                                <IconInfo className="shrink-0 text-secondary" />
                            </Tooltip>
                        )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        {sampleData && <SampleDataTag />}
                        {control}
                        <LemonButton
                            type="tertiary"
                            size="small"
                            to={getHomeTabExploreUrl(option.query)}
                            data-attr={`home-tab-explore-${option.key}`}
                        >
                            Explore
                        </LemonButton>
                    </div>
                </div>
                <Tooltip title={option.description}>
                    <p className="m-0 mt-0.5 text-xs text-secondary">{option.description}</p>
                </Tooltip>
            </div>
            <div
                className={`HomeTabDefaultChart HomeTabChartCard__visualization HomeTabChartCard__visualization--${size}`}
            >
                {chart}
            </div>
        </LemonCard>
    )
}
