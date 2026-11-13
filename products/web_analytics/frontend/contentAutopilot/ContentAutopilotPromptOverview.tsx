import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import type { AEOPromptStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotAnswerOutcomeChart } from './ContentAutopilotAnswerOutcomeChart'
import { ContentAutopilotEngineTable } from './ContentAutopilotEngineTable'
import { ContentAutopilotPromptConsensus } from './ContentAutopilotPromptConsensus'
import type { PromptReportTab } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotSentimentBar } from './ContentAutopilotSentimentBar'
import type {
    PromptConsensusMatrix,
    PromptOutcomeMetric,
    PromptReportKpis,
    PromptSentimentSummary,
} from './promptReport'
import { sortEngines } from './utils'
import type { AnswerOutcomeChart } from './visibilityChart'

const ViewAllButton = ({
    label,
    onClick,
    'data-attr': dataAttr,
}: {
    label: string
    onClick: () => void
    'data-attr': string
}): JSX.Element => (
    <LemonButton size="small" type="tertiary" onClick={onClick} data-attr={dataAttr}>
        {label}
    </LemonButton>
)

/** The prompt's report at a glance: answers over time, each engine's results, tone, who gets cited and what the
 *  engines searched for. Each tile links to the tab with the full detail. */
export const ContentAutopilotPromptOverview = ({
    stats,
    kpis,
    chart,
    metric,
    onMetricChange,
    query,
    consensus,
    sentiment,
    onOpenTab,
}: {
    stats: AEOPromptStatsApi
    kpis: PromptReportKpis
    chart: AnswerOutcomeChart
    metric: PromptOutcomeMetric
    onMetricChange: (metric: PromptOutcomeMetric) => void
    query: DataVisualizationNode
    consensus: PromptConsensusMatrix
    sentiment: PromptSentimentSummary
    onOpenTab: (tab: PromptReportTab) => void
}): JSX.Element => {
    const engineOrder = sortEngines(stats.engines.map(({ engine }) => engine))
    const engines = stats.engines
        .filter((engine) => engine.checks - engine.failed > 0)
        .sort((a, b) => engineOrder.indexOf(a.engine) - engineOrder.indexOf(b.engine))

    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-prompt-overview">
            <ContentAutopilotAnswerOutcomeChart
                chart={chart}
                metric={metric}
                onMetricChange={onMetricChange}
                query={query}
                description={`${pluralize(kpis.answers, 'answer')} across ${pluralize(kpis.days, 'day')}, from every engine. Failed checks are left out.`}
                data-attr="content-autopilot-prompt-visibility-tile"
            />
            <div className="grid grid-cols-1 @3xl/prompt-report:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="By engine"
                        description="How each engine answered this prompt. Failed checks are left out."
                    />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompt-overview-engines">
                        <ContentAutopilotEngineTable engines={engines} />
                    </div>
                </PagePerformanceCard>
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="How the answers speak about you"
                        description="Scored on the sentences that name you, so praise of another tool doesn't count."
                        actions={
                            <ViewAllButton
                                label="View sentiment"
                                onClick={() => onOpenTab('sentiment')}
                                data-attr="content-autopilot-prompt-overview-sentiment-more"
                            />
                        }
                    />
                    <div className="p-3" data-attr="content-autopilot-prompt-overview-sentiment">
                        <ContentAutopilotSentimentBar summary={sentiment} />
                    </div>
                </PagePerformanceCard>
            </div>
            <PagePerformanceCard className="min-w-0">
                <PagePerformanceCardHeader
                    title="Cited sites by engine"
                    description="The share of each engine's answers that link to a site. A darker cell means the engine links to that site more often."
                    actions={
                        <ViewAllButton
                            label="View sources"
                            onClick={() => onOpenTab('sources')}
                            data-attr="content-autopilot-prompt-overview-sources-more"
                        />
                    }
                />
                <div className="p-3 overflow-x-auto" data-attr="content-autopilot-prompt-overview-consensus">
                    <ContentAutopilotPromptConsensus matrix={consensus} />
                </div>
            </PagePerformanceCard>
            {stats.top_words.length ? (
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="Words the engines searched for"
                        description="The most common words in the web searches the engines ran before answering."
                        actions={
                            <ViewAllButton
                                label="View searches"
                                onClick={() => onOpenTab('searches')}
                                data-attr="content-autopilot-prompt-overview-searches-more"
                            />
                        }
                    />
                    <div
                        className="p-3 flex flex-wrap items-center gap-1"
                        data-attr="content-autopilot-prompt-overview-searches"
                    >
                        {stats.top_words.map((word) => (
                            <LemonTag key={word.word} size="small">
                                {word.word} <span className="text-muted">{word.count}</span>
                            </LemonTag>
                        ))}
                    </div>
                </PagePerformanceCard>
            ) : null}
        </div>
    )
}
