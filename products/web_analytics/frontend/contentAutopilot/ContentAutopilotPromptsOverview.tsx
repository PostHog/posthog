import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { OVERVIEW_DAYS, contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { ContentAutopilotPromptsOverviewSkeleton } from './ContentAutopilotPromptsOverviewSkeleton'
import { ContentAutopilotPromptsSearchTable } from './ContentAutopilotPromptsSearchTable'
import { ContentAutopilotPromptsTopicTable } from './ContentAutopilotPromptsTopicTable'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { ContentAutopilotVisibilityDashboardButton } from './ContentAutopilotVisibilityDashboardButton'
import { POSITION_DESCRIPTION } from './promptReport'
import { promptSourcesContext } from './promptReportColumns'
import { brandedAnswersNote, engineLabel, segmentPrompts } from './utils'

export const ContentAutopilotPromptsOverview = (): JSX.Element => {
    const { overview, overviewLoading, overviewError, overviewKpis, hasChecks, citationQuery, sourcesQuery } =
        useValues(contentAutopilotPromptsOverviewLogic)
    const { loadPromptSetOverview, selectOverviewTopic, openOverviewSearchPrompt } = useActions(
        contentAutopilotPromptsOverviewLogic
    )
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
    if (!overview || !overviewKpis || !citationQuery || !sourcesQuery) {
        return <ContentAutopilotPromptsOverviewSkeleton />
    }
    const header = (
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 basis-80">
                <h4 className="m-0">Last {OVERVIEW_DAYS} days, all engines</h4>
                <p className="m-0 text-xs text-muted" data-attr="content-autopilot-prompts-overview-answers">
                    {brandedAnswersNote(overview.branded, overview.current.checks - overview.current.failed)} Each
                    number is compared with the {OVERVIEW_DAYS} days before.
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

    const engineTotals = overview.engines.filter((engine) => engine.checks - engine.failed > 0)

    return (
        <section
            className="@container/prompts-overview flex flex-col gap-4"
            data-attr="content-autopilot-prompts-overview"
        >
            {header}
            <div className="grid grid-cols-2 @3xl/prompts-overview:grid-cols-3 @7xl/prompts-overview:grid-cols-5 gap-3">
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
                    description="Share of answers that name your brand, with or without a link. An answer that cites your site always counts as a mention."
                    {...overviewKpis.mentionRate}
                    data-attr="content-autopilot-prompts-overview-kpi-mentioned"
                />
                <ContentAutopilotPromptKpiCard
                    label="Cited as a source"
                    description="Share of answers that link to a page on your site as a source, so people can click through to it."
                    {...overviewKpis.citationRate}
                    data-attr="content-autopilot-prompts-overview-kpi-cited"
                />
                <ContentAutopilotPromptKpiCard
                    label="Average position"
                    description={POSITION_DESCRIPTION}
                    {...overviewKpis.position}
                    data-attr="content-autopilot-prompts-overview-kpi-position"
                />
            </div>

            <ContentAutopilotPromptQueryTile
                title="Cited as a source over time"
                query={citationQuery}
                uniqueKey={`aeo-prompt-set-citations-${overview.branded}`}
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
                    uniqueKey={`aeo-prompt-set-sources-${overview.branded}`}
                    context={promptSourcesContext}
                    footer={`Your site: ${overview.target_domains.join(', ')}`}
                    data-attr="content-autopilot-prompts-overview-sources-tile"
                />
            </div>

            <PagePerformanceCard className="min-w-0">
                <PagePerformanceCardHeader title="What the engines searched for" />
                <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-searches">
                    <ContentAutopilotPromptsSearchTable
                        rows={overview.top_searches}
                        onOpenPrompt={openOverviewSearchPrompt}
                    />
                </div>
            </PagePerformanceCard>
        </section>
    )
}
