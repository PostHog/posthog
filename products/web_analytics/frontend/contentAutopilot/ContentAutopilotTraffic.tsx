import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { TileId } from 'scenes/web-analytics/common'
import { webAnalyticsDateMapping } from 'scenes/web-analytics/constants'
import { WebConversionGoal } from 'scenes/web-analytics/WebConversionGoal'

import { AiTableCard } from 'products/web_analytics/frontend/searchAndAi/AiTableCard'

import type { AiTrafficTrendMetric } from './aiTraffic'
import { contentAutopilotAiTrafficLogic } from './contentAutopilotAiTrafficLogic'
import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotTrafficEmptyState } from './ContentAutopilotTrafficEmptyState'
import { ContentAutopilotTrafficPages } from './ContentAutopilotTrafficPages'

const formatRate = (rate: number | null): string => (rate === null ? '-' : `${rate.toFixed(1)}%`)

const ConversionKpi = (): JSX.Element => {
    const { conversionGoal, conversion, conversionLoading, conversionError } = useValues(contentAutopilotAiTrafficLogic)

    const content = !conversionGoal
        ? { value: '-', note: 'Pick a conversion goal to compare' }
        : conversionError
          ? { value: '-', note: "Couldn't load conversions" }
          : !conversion || conversionLoading
            ? { value: '…', note: 'Loading conversions' }
            : { value: formatRate(conversion.aiRate), note: `All visitors: ${formatRate(conversion.allRate)}` }

    return (
        <ContentAutopilotPromptKpiCard
            label="Conversion rate from AI"
            description="Share of visitors from AI assistants who completed the conversion goal, next to the same rate for all visitors."
            delta={null}
            {...content}
            data-attr="content-autopilot-ai-traffic-kpi-conversion"
        />
    )
}

/** Visits that AI assistants send to the site, next to the pages the engines cite in prompt checks. */
export const ContentAutopilotTraffic = (): JSX.Element => {
    const {
        dateFrom,
        dateTo,
        conversionGoal,
        summary,
        summaryError,
        summaryLoading,
        trendQuery,
        trendMetric,
        entryPagesQuery,
    } = useValues(contentAutopilotAiTrafficLogic)
    const { setDateRange, setConversionGoal, setTrendMetric, reload } = useActions(contentAutopilotAiTrafficLogic)
    const share = summary && summary.allSessions > 0 ? summary.aiSessions / summary.allSessions : null

    return (
        <section className="@container/ai-traffic flex flex-col gap-4" data-attr="content-autopilot-ai-traffic">
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={reload}
                    loading={summaryLoading}
                    aria-label="Reload AI traffic"
                    data-attr="content-autopilot-ai-traffic-reload"
                />
                <DateFilter
                    dateOptions={webAnalyticsDateMapping}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={setDateRange}
                />
                <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
            </div>

            {summaryError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: reload, loading: summaryLoading }}>
                    Couldn't load traffic from AI assistants. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !summary ? (
                <LemonSkeleton className="h-32 w-full" />
            ) : summary.aiSessions === 0 ? (
                <ContentAutopilotTrafficEmptyState />
            ) : (
                <>
                    <div className="grid grid-cols-1 @xl/ai-traffic:grid-cols-3 gap-3">
                        <ContentAutopilotPromptKpiCard
                            label="Visitors from AI"
                            description="Unique visitors whose session started from an AI assistant's answer."
                            value={humanFriendlyNumber(summary.aiVisitors)}
                            note="Referred by an AI assistant"
                            delta={null}
                            data-attr="content-autopilot-ai-traffic-kpi-visitors"
                        />
                        <ContentAutopilotPromptKpiCard
                            label="Sessions from AI"
                            description="Sessions that started from an AI assistant's answer."
                            value={humanFriendlyNumber(summary.aiSessions)}
                            note={
                                share === null ? 'No sessions in this range' : `${percentage(share, 1)} of all sessions`
                            }
                            delta={null}
                            data-attr="content-autopilot-ai-traffic-kpi-sessions"
                        />
                        <ConversionKpi />
                    </div>

                    <ContentAutopilotPromptQueryTile
                        title={trendMetric === 'visitors' ? 'Visitors from AI over time' : 'Sessions from AI over time'}
                        query={trendQuery}
                        uniqueKey="aeo-ai-traffic-trend"
                        bodyClassName="h-80 p-2"
                        actions={
                            <LemonSegmentedButton<AiTrafficTrendMetric>
                                size="small"
                                value={trendMetric}
                                onChange={setTrendMetric}
                                options={[
                                    { value: 'visitors', label: 'Visitors' },
                                    { value: 'sessions', label: 'Sessions' },
                                ]}
                                data-attr="content-autopilot-ai-traffic-metric"
                            />
                        }
                        data-attr="content-autopilot-ai-traffic-trend-tile"
                    />

                    <AiTableCard
                        title="Top landing pages from AI"
                        query={entryPagesQuery}
                        tileId={TileId.AI_LANDING_PAGES}
                        scope="ai-visibility"
                        tableLayout="auto"
                    />

                    <ContentAutopilotTrafficPages />
                </>
            )}
        </section>
    )
}
