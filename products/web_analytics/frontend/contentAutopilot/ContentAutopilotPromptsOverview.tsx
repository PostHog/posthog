import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { OVERVIEW_DAYS, contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { ContentAutopilotPromptsTopicTable } from './ContentAutopilotPromptsTopicTable'
import { promptSourcesContext } from './promptReportColumns'
import { engineLabel } from './utils'

export const ContentAutopilotPromptsOverview = (): JSX.Element | null => {
    const { overview, overviewLoading, overviewError, overviewKpis, hasChecks, citationQuery, sourcesQuery } =
        useValues(contentAutopilotPromptsOverviewLogic)
    const { loadPromptSetOverview, selectOverviewTopic } = useActions(contentAutopilotPromptsOverviewLogic)
    const { promptsTopic } = useValues(contentAutopilotPromptsLogic)

    // The list below already explains that the feature is off, so the overview says nothing twice.
    if (overviewError === 'forbidden') {
        return null
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
    if (!overview || !overviewKpis || !citationQuery || !sourcesQuery) {
        return <LemonSkeleton className="h-32 w-full" />
    }
    if (!hasChecks) {
        // Without prompts, the list below shows how to add some.
        return overview.prompts_tracked === 0 ? null : (
            <LemonCard hoverEffect={false} className="p-4" data-attr="content-autopilot-prompts-overview-empty">
                <h4 className="m-0">No checks yet</h4>
                <p className="m-0 mt-1 text-muted">The daily run fills this in.</p>
            </LemonCard>
        )
    }

    const engineTotals = overview.engines.filter((engine) => engine.checks - engine.failed > 0)

    return (
        <section
            className="@container/prompts-overview flex flex-col gap-4"
            data-attr="content-autopilot-prompts-overview"
        >
            <div>
                <h4 className="m-0">Last {OVERVIEW_DAYS} days, all engines</h4>
                <p className="m-0 text-xs text-muted">Each number is compared with the {OVERVIEW_DAYS} days before.</p>
            </div>
            <div className="grid grid-cols-2 @3xl/prompts-overview:grid-cols-4 gap-3">
                <ContentAutopilotPromptKpiCard
                    label="Prompts tracked"
                    description="Prompts that are on and not archived. The next daily run checks them."
                    {...overviewKpis.promptsTracked}
                    data-attr="content-autopilot-prompts-overview-kpi-prompts"
                />
                <ContentAutopilotPromptKpiCard
                    label="Checks run"
                    description="One check is one prompt sent to one engine. Failed checks are counted here and left out of the rates."
                    {...overviewKpis.checks}
                    data-attr="content-autopilot-prompts-overview-kpi-checks"
                />
                <ContentAutopilotPromptKpiCard
                    label="Mentioned in answers"
                    description="Share of answers that name you. An answer that cites your site always counts."
                    {...overviewKpis.mentionRate}
                    data-attr="content-autopilot-prompts-overview-kpi-mentioned"
                />
                <ContentAutopilotPromptKpiCard
                    label="Cited as a source"
                    description="Share of answers that link to a page on your site."
                    {...overviewKpis.citationRate}
                    data-attr="content-autopilot-prompts-overview-kpi-cited"
                />
            </div>

            <ContentAutopilotPromptQueryTile
                title="Cited as a source over time"
                query={citationQuery}
                uniqueKey="aeo-prompt-set-citations"
                bodyClassName="h-72 p-2"
                footer={
                    engineTotals.length ? (
                        <span className="flex flex-wrap gap-x-4 gap-y-1">
                            {engineTotals.map((engine) => (
                                <span key={engine.engine} className="whitespace-nowrap">
                                    {engineLabel(engine.engine)}:{' '}
                                    <span className="tabular-nums">
                                        {engine.citation_rate === null ? '-' : percentage(engine.citation_rate, 0)}
                                    </span>{' '}
                                    of {pluralize(engine.checks - engine.failed, 'answer')}
                                </span>
                            ))}
                        </span>
                    ) : undefined
                }
                data-attr="content-autopilot-prompts-overview-citations-tile"
            />

            <div className="grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4">
                <PagePerformanceCard className="min-w-0">
                    <PagePerformanceCardHeader title="Mentions by topic" />
                    <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-topics">
                        <ContentAutopilotPromptsTopicTable
                            rows={overview.topics}
                            selectedTopic={promptsTopic}
                            onSelect={selectOverviewTopic}
                        />
                    </div>
                </PagePerformanceCard>
                <ContentAutopilotPromptQueryTile
                    title="Sites the engines cite most"
                    query={sourcesQuery}
                    uniqueKey="aeo-prompt-set-sources"
                    context={promptSourcesContext}
                    footer={`Your site: ${overview.target_domains.join(', ')}`}
                    data-attr="content-autopilot-prompts-overview-sources-tile"
                />
            </div>
        </section>
    )
}
