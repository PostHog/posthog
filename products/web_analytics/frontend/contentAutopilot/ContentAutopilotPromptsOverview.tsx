import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import { ContentAutopilotCitedSitesTable } from './ContentAutopilotCitedSitesTable'
import { ContentAutopilotEngineTable } from './ContentAutopilotEngineTable'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { OVERVIEW_DAYS, contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { ContentAutopilotPromptsOverviewSkeleton } from './ContentAutopilotPromptsOverviewSkeleton'
import { ContentAutopilotPromptsSearchTable } from './ContentAutopilotPromptsSearchTable'
import { ContentAutopilotPromptsTopicTable } from './ContentAutopilotPromptsTopicTable'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ContentAutopilotVisibilityChart } from './ContentAutopilotVisibilityChart'
import { ContentAutopilotVisibilityDashboardButton } from './ContentAutopilotVisibilityDashboardButton'
import { POSITION_DESCRIPTION } from './promptReport'
import { brandedAnswersNote, segmentPrompts, sortEngines } from './utils'

export const ContentAutopilotPromptsOverview = (): JSX.Element => {
    const {
        overview,
        overviewLoading,
        overviewError,
        overviewKpis,
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
    const { promptsTopic } = useValues(contentAutopilotPromptsLogic)
    const { openAddPrompts } = useActions(contentAutopilotPromptsLogic)

    if (overviewError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }
    if (overviewError === 'failed') {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadPromptSetOverview, loading: overviewLoading }}
            >
                Couldn't load the overview. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (!overview || !overviewKpis || !visibilityChart || !visibilityQuery || !sourcesQuery) {
        return <ContentAutopilotPromptsOverviewSkeleton />
    }
    const header = (
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 basis-80">
                <h3 className="m-0 text-sm font-semibold">Last {OVERVIEW_DAYS} days, all engines</h3>
                <p className="m-0 text-xs text-secondary" data-attr="content-autopilot-prompts-overview-answers">
                    {brandedAnswersNote(overview.branded, overview.current.checks - overview.current.failed)}{' '}
                    {overview.current.failed
                        ? `${pluralize(overview.current.failed, 'check')} failed and ${overview.current.failed === 1 ? 'is' : 'are'} left out. `
                        : ''}
                    Each number is compared with the {OVERVIEW_DAYS} days before.
                </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <ContentAutopilotBrandedSegmentControl tab="overview" />
                <ContentAutopilotVisibilityDashboardButton />
            </div>
        </div>
    )
    if (!hasChecks && overview.branded_answers + overview.non_branded_answers > 0) {
        return (
            <section className="flex flex-col gap-4" data-attr="content-autopilot-prompts-overview">
                {header}
                <LemonCard
                    hoverEffect={false}
                    className="p-4"
                    data-attr="content-autopilot-prompts-overview-segment-empty"
                >
                    <h4 className="m-0">
                        No answers to {segmentPrompts(overview.branded)} in the last {OVERVIEW_DAYS} days
                    </h4>
                    <p className="m-0 mt-1 text-muted">Choose another option above to see the other answers.</p>
                </LemonCard>
            </section>
        )
    }
    if (!hasChecks) {
        return overview.prompts_tracked === 0 ? (
            <LemonCard
                hoverEffect={false}
                className="p-6 text-center"
                data-attr="content-autopilot-prompts-overview-no-prompts"
            >
                <h3 className="m-0">No prompts yet</h3>
                <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                    Add the questions your buyers ask AI assistants. Claude can suggest them from your site, or you can
                    write your own. PostHog checks them once a day and shows the results here.
                </p>
                <div className="mt-4 flex justify-center gap-2">
                    <ContentAutopilotPromptSuggestButton type="primary" />
                    <LemonButton
                        type="secondary"
                        icon={<IconPlusSmall />}
                        onClick={openAddPrompts}
                        data-attr="content-autopilot-prompts-overview-add"
                    >
                        Add my own
                    </LemonButton>
                </div>
            </LemonCard>
        ) : (
            <LemonCard hoverEffect={false} className="p-4" data-attr="content-autopilot-prompts-overview-empty">
                <h4 className="m-0">No checks yet</h4>
                <p className="m-0 mt-1 text-muted">The daily run fills this in.</p>
            </LemonCard>
        )
    }

    // The chart's legend order, so an engine sits in the same place in the chart and the table.
    const engineOrder = sortEngines(overview.engines.map(({ engine }) => engine))
    const engines = overview.engines
        .filter((engine) => engine.checks - engine.failed > 0)
        .sort((a, b) => engineOrder.indexOf(a.engine) - engineOrder.indexOf(b.engine))

    return (
        <section
            className="@container/prompts-overview flex flex-col gap-4"
            data-attr="content-autopilot-prompts-overview"
        >
            {header}
            <ContentAutopilotStatStrip
                className="grid-cols-2 @3xl/prompts-overview:grid-cols-4"
                data-attr="content-autopilot-prompts-overview-kpis"
            >
                <ContentAutopilotKpiStat
                    label="Prompts tracked"
                    description="Prompts that are on and not archived. The next daily run checks them."
                    {...overviewKpis.promptsTracked}
                    onClick={() => setWorkspaceTab('prompts')}
                    data-attr="content-autopilot-prompts-overview-kpi-prompts"
                />
                <ContentAutopilotKpiStat
                    label="Mentioned in answers"
                    description="Share of answers that name your brand, with or without a link. An answer that cites your site always counts as a mention."
                    {...overviewKpis.mentionRate}
                    onClick={() => setChartMetric('mentioned')}
                    data-attr="content-autopilot-prompts-overview-kpi-mentioned"
                />
                <ContentAutopilotKpiStat
                    label="Cited as a source"
                    description="Share of answers that link to a page on your site as a source, so people can click through to it."
                    {...overviewKpis.citationRate}
                    onClick={() => setChartMetric('cited')}
                    data-attr="content-autopilot-prompts-overview-kpi-cited"
                />
                <ContentAutopilotKpiStat
                    label="Average position"
                    description={POSITION_DESCRIPTION}
                    {...overviewKpis.position}
                    onClick={() => setChartMetric('position')}
                    data-attr="content-autopilot-prompts-overview-kpi-position"
                />
            </ContentAutopilotStatStrip>

            <ContentAutopilotVisibilityChart
                chart={visibilityChart}
                metric={chartMetric}
                onMetricChange={setChartMetric}
                query={visibilityQuery}
                description="One line per engine, one point per day. Failed checks are left out."
                data-attr="content-autopilot-prompts-overview-visibility"
            />

            <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="By engine"
                        description={`Each engine's answers to your prompts over the last ${OVERVIEW_DAYS} days. Failed checks are left out.`}
                    />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-engines">
                        <ContentAutopilotEngineTable engines={engines} />
                    </div>
                </PagePerformanceCard>
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="Mentions by topic"
                        description="Pick a topic to see its prompts."
                    />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-topics">
                        <ContentAutopilotPromptsTopicTable
                            rows={overview.topics}
                            selectedTopic={promptsTopic}
                            onSelect={selectOverviewTopic}
                        />
                    </div>
                </PagePerformanceCard>
            </div>

            <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="Sites the engines cite most"
                        actions={
                            <ContentAutopilotOpenInsightButton
                                query={sourcesQuery}
                                data-attr="content-autopilot-prompts-overview-sources-tile-open-insight"
                            />
                        }
                    />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-sources-tile">
                        <ContentAutopilotCitedSitesTable domains={overview.top_domains} />
                    </div>
                </PagePerformanceCard>
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader
                        title="What the engines searched for"
                        description="The web searches the engines ran while answering your prompts. Expand one to see its prompts."
                    />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-searches">
                        <ContentAutopilotPromptsSearchTable
                            rows={overview.top_searches}
                            onOpenPrompt={openOverviewSearchPrompt}
                        />
                    </div>
                </PagePerformanceCard>
            </div>
        </section>
    )
}
