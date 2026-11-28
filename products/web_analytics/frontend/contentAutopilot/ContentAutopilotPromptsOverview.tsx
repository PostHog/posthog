import { useActions, useValues } from 'kea'

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, cn } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilitySetupWizard } from './AiVisibilitySetupWizard'
import { ContentAutopilotCitedSitesTable } from './ContentAutopilotCitedSitesTable'
import { ContentAutopilotEngineTable } from './ContentAutopilotEngineTable'
import { ContentAutopilotEngineTopicHeatmap } from './ContentAutopilotEngineTopicHeatmap'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { ContentAutopilotFirstRunCard } from './ContentAutopilotFirstRunCard'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotMovers } from './ContentAutopilotMovers'
import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { ContentAutopilotPromptsOverviewSkeleton } from './ContentAutopilotPromptsOverviewSkeleton'
import { ContentAutopilotPromptsSearchTable } from './ContentAutopilotPromptsSearchTable'
import { ContentAutopilotPromptsTopicTable } from './ContentAutopilotPromptsTopicTable'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotVisibilityChart } from './ContentAutopilotVisibilityChart'
import { POSITION_DESCRIPTION } from './promptReport'
import { engineTopicGrid, overviewTiles } from './promptsOverview'
import { brandedAnswersNote, segmentPrompts, sortEngines, windowRange } from './utils'

export const ContentAutopilotPromptsOverview = (): JSX.Element => {
    const {
        overview,
        overviewLoading,
        overviewError,
        hasChecks,
        chartMetric,
        visibilityChart,
        visibilityQuery,
        sourcesQuery,
    } = useValues(contentAutopilotPromptsOverviewLogic)
    const { loadPromptSetOverview, selectOverviewTopic, openOverviewSearchPrompt, setChartMetric } = useActions(
        contentAutopilotPromptsOverviewLogic
    )
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const { topic } = useValues(contentAutopilotFiltersLogic)
    const { setupContext, wizardStep } = useValues(contentAutopilotSetupLogic)

    if (overviewError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }
    if (overviewError === 'failed') {
        return (
            <AiVisibilityBanner
                type="error"
                action={{ children: 'Try again', onClick: loadPromptSetOverview, loading: overviewLoading }}
            >
                Couldn't load the overview. Try again, and if it keeps happening contact support.
            </AiVisibilityBanner>
        )
    }
    if (wizardStep) {
        return <AiVisibilitySetupWizard step={wizardStep} />
    }
    if (!setupContext || !overview || !visibilityChart || !visibilityQuery || !sourcesQuery) {
        return <ContentAutopilotPromptsOverviewSkeleton />
    }
    const narrowed = overview.engine !== null || overview.topic !== null
    if (!hasChecks && (narrowed || overview.branded_answers + overview.non_branded_answers > 0)) {
        return (
            <section className="flex flex-col gap-4" data-attr="content-autopilot-prompts-overview">
                <Empty data-attr="content-autopilot-prompts-overview-segment-empty">
                    <EmptyHeader>
                        <EmptyTitle>
                            No answers to {segmentPrompts(overview.branded)} {windowRange(overview)}
                            {narrowed ? ' that match these filters' : ''}
                        </EmptyTitle>
                        <EmptyDescription>Choose other filters above to see the other answers.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </section>
        )
    }
    if (!hasChecks) {
        const paused = setupContext?.paused_prompts ?? 0
        // The filter bar can hide every prompt from the overview's count, so the project's own count decides.
        if ((setupContext?.active_prompts ?? overview.prompts_tracked) > 0) {
            return <ContentAutopilotFirstRunCard prompts={setupContext?.active_prompts ?? overview.prompts_tracked} />
        }
        return <ContentAutopilotFirstRunCard prompts={paused} paused />
    }

    const tiles = overviewTiles(overview)
    // The tiles show only their value, so the answers they come from are in each rate's tooltip.
    const base = [
        brandedAnswersNote(overview.branded, overview.current.checks - overview.current.failed),
        overview.current.failed
            ? `${pluralize(overview.current.failed, 'check')} failed and ${overview.current.failed === 1 ? 'is' : 'are'} left out.`
            : '',
    ]
        .filter(Boolean)
        .join(' ')

    // The chart's legend order, so an engine sits in the same place in the chart and the table.
    const engineOrder = sortEngines(overview.engines.map(({ engine }) => engine))
    const engines = overview.engines
        .filter((engine) => engine.checks - engine.failed > 0)
        .sort((a, b) => engineOrder.indexOf(a.engine) - engineOrder.indexOf(b.engine))

    return (
        <section
            className={cn(
                '@container/prompts-overview flex flex-col gap-4 transition-opacity motion-reduce:transition-none',
                // The numbers on screen belong to the previous filters until the new overview arrives.
                overviewLoading && 'opacity-50'
            )}
            aria-busy={overviewLoading}
            data-attr="content-autopilot-prompts-overview"
        >
            <ContentAutopilotStatStrip
                className="grid-cols-2 @3xl/prompts-overview:grid-cols-4"
                data-attr="content-autopilot-prompts-overview-kpis"
            >
                <ContentAutopilotKpiStat
                    label="Prompts tracked"
                    description="Paused and archived prompts don't count."
                    value={tiles.prompts}
                    onClick={() => setWorkspaceTab('prompts')}
                    data-attr="content-autopilot-prompts-overview-kpi-prompts"
                />
                <ContentAutopilotKpiStat
                    label="Visibility"
                    description={`Share of answers that name your brand or link to your site. ${base}`}
                    value={tiles.visibility}
                    onClick={() => setChartMetric('mentioned')}
                    data-attr="content-autopilot-prompts-overview-kpi-mentioned"
                />
                <ContentAutopilotKpiStat
                    label="Cited as a source"
                    description={`Share of answers that link to a page on your site. ${base}`}
                    value={tiles.cited}
                    onClick={() => setChartMetric('cited')}
                    data-attr="content-autopilot-prompts-overview-kpi-cited"
                />
                <ContentAutopilotKpiStat
                    label="Average position"
                    description={`${POSITION_DESCRIPTION} ${base}`}
                    value={tiles.position}
                    onClick={() => setChartMetric('position')}
                    data-attr="content-autopilot-prompts-overview-kpi-position"
                />
            </ContentAutopilotStatStrip>

            <ContentAutopilotVisibilityChart
                chart={visibilityChart}
                metric={chartMetric}
                onMetricChange={setChartMetric}
                query={visibilityQuery}
                data-attr="content-autopilot-prompts-overview-visibility"
            />

            <ContentAutopilotMovers />

            <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
                <AiVisibilityCard title="By engine">
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-engines">
                        <ContentAutopilotEngineTable engines={engines} />
                    </div>
                </AiVisibilityCard>
                <AiVisibilityCard title="Visibility by topic">
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-topics">
                        <ContentAutopilotPromptsTopicTable
                            rows={overview.topics}
                            selectedTopic={topic}
                            onSelect={selectOverviewTopic}
                        />
                    </div>
                </AiVisibilityCard>
            </div>

            <ContentAutopilotEngineTopicHeatmap
                grid={engineTopicGrid(overview)}
                selectedTopic={topic}
                onSelectTopic={selectOverviewTopic}
            />

            <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
                <AiVisibilityCard
                    title="Sites the engines cite most"
                    actions={
                        <ContentAutopilotOpenInsightButton
                            query={sourcesQuery}
                            data-attr="content-autopilot-prompts-overview-sources-tile-open-insight"
                        />
                    }
                >
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-sources-tile">
                        <ContentAutopilotCitedSitesTable
                            domains={overview.top_domains}
                            dateFrom={overview.window_from}
                            dateTo={overview.window_to}
                            branded={overview.branded}
                        />
                    </div>
                </AiVisibilityCard>
                <AiVisibilityCard title="What the engines searched for">
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-searches">
                        <ContentAutopilotPromptsSearchTable
                            rows={overview.top_searches}
                            dateFrom={overview.window_from}
                            dateTo={overview.window_to}
                            branded={overview.branded}
                            engine={overview.engine}
                            topic={overview.topic}
                            onOpenPrompt={openOverviewSearchPrompt}
                        />
                    </div>
                </AiVisibilityCard>
            </div>
        </section>
    )
}
