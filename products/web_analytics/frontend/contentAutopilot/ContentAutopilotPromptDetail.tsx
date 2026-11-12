import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSkeleton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotDraftButton } from './ContentAutopilotDraftButton'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPageHeader } from './ContentAutopilotPageHeader'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptAnswer } from './ContentAutopilotPromptAnswer'
import { ContentAutopilotPromptArchiveBanner } from './ContentAutopilotPromptArchiveBanner'
import { ContentAutopilotPromptChecks } from './ContentAutopilotPromptChecks'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptEditModal } from './ContentAutopilotPromptEditModal'
import { ContentAutopilotPromptOverview } from './ContentAutopilotPromptOverview'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotPromptSentiment } from './ContentAutopilotPromptSentiment'
import { ContentAutopilotPromptVersions } from './ContentAutopilotPromptVersions'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { POSITION_DESCRIPTION, positionKpiCard, rateKpiCard } from './promptReport'
import { promptCitationsContext, promptSearchesContext, promptSourcesContext } from './promptReportColumns'
import { draftableOpportunity } from './utils'

const TabSection = ({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element => (
    <section className="flex flex-col gap-3">
        <div>
            <h3 className="m-0 text-sm font-semibold">{title}</h3>
            {description ? <p className="m-0 text-xs text-secondary">{description}</p> : null}
        </div>
        {children}
    </section>
)

/** One prompt's report, on its own URL in place of the workspace tabs. */
export const ContentAutopilotPromptDetail = (): JSX.Element | null => {
    const {
        promptId,
        prompt,
        stats,
        lastCheckedAt,
        detailError,
        archiveConfirming,
        reportKpis,
        reportTab,
        consensusMatrix,
        sentimentSummary,
        visibilityMetric,
        visibilityChart,
        visibilityQuery,
        sourcesQuery,
        citationsQuery,
        searchesQuery,
        sentimentQuery,
    } = useValues(contentAutopilotPromptDetailLogic)
    const {
        closePromptDetail,
        openPromptDetail,
        setArchiveConfirming,
        setPromptEditing,
        setReportTab,
        setVisibilityMetric,
    } = useActions(contentAutopilotPromptDetailLogic)
    const { opportunityByPromptId, draftingEnabled } = useValues(contentAutopilotLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const draftOpportunity = prompt && draftingEnabled ? draftableOpportunity(opportunityByPromptId, prompt) : null
    const backToPrompts = (): void => setWorkspaceTab('prompts')

    if (!promptId) {
        return null
    }

    if (detailError === 'not_found') {
        return (
            <div className="flex flex-col gap-4" data-attr="content-autopilot-prompt-page">
                <ContentAutopilotPageHeader
                    title="Prompt not found"
                    backLabel="Prompts"
                    backDataAttr="content-autopilot-prompt-back"
                    onBack={backToPrompts}
                />
                <p className="m-0">This prompt isn't in the project's prompt set anymore, or the link is wrong.</p>
            </div>
        )
    }

    const reportReady =
        prompt &&
        stats &&
        reportKpis &&
        consensusMatrix &&
        sentimentSummary &&
        visibilityChart &&
        visibilityQuery &&
        sourcesQuery &&
        citationsQuery &&
        searchesQuery &&
        sentimentQuery

    const showMetric = (metric: typeof visibilityMetric): void => {
        setVisibilityMetric(metric)
        setReportTab('overview')
    }

    const actions =
        prompt && !prompt.archived_at ? (
            <>
                {draftOpportunity ? (
                    <ContentAutopilotDraftButton opportunity={draftOpportunity} onReview={closePromptDetail} />
                ) : null}
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setPromptEditing(true)}
                    data-attr="content-autopilot-prompt-edit"
                >
                    Edit
                </LemonButton>
                <LemonMenu
                    items={[
                        {
                            label: 'Copy link to this prompt',
                            onClick: () => void copyToClipboard(window.location.href, 'link to this prompt'),
                        },
                        {
                            label: 'Archive',
                            status: 'danger',
                            onClick: () => setArchiveConfirming(true),
                            disabledReason: archiveConfirming ? 'Confirm or cancel below' : undefined,
                            'data-attr': 'content-autopilot-prompt-archive',
                        },
                    ]}
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconEllipsis />}
                        aria-label="More actions"
                        data-attr="content-autopilot-prompt-more"
                    />
                </LemonMenu>
            </>
        ) : null

    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-prompt-page">
            <ContentAutopilotPageHeader
                title={prompt?.prompt ?? 'Loading prompt'}
                backLabel="Prompts"
                backDataAttr="content-autopilot-prompt-back"
                onBack={backToPrompts}
                actions={actions}
            />
            {detailError === 'failed' ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => openPromptDetail(promptId) }}>
                    Couldn't load this prompt. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !reportReady ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-6 w-1/2" />
                    <LemonSkeleton className="h-20 w-full" />
                    <LemonSkeleton className="h-72 w-full" />
                </div>
            ) : (
                <div className="@container/prompt-report flex flex-col gap-4">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                        {prompt.topic ? (
                            <LemonTag>{prompt.topic}</LemonTag>
                        ) : (
                            <LemonTag type="muted">No topic</LemonTag>
                        )}
                        <LemonTag type="muted">Version {prompt.current_version}</LemonTag>
                        {prompt.archived_at ? (
                            <LemonTag type="muted">Archived</LemonTag>
                        ) : (
                            <ContentAutopilotPromptActiveSwitch
                                promptId={prompt.id}
                                active={prompt.active}
                                label="Active"
                            />
                        )}
                        <span className="text-secondary">
                            Last checked {lastCheckedAt ? <TZLabel time={lastCheckedAt} /> : 'never'}
                        </span>
                        <span className="text-secondary">{pluralize(stats.total_checks, 'check')} in total</span>
                    </div>
                    <ContentAutopilotPromptArchiveBanner />

                    {stats.engines.length === 0 ? (
                        <p className="m-0 text-secondary">
                            This prompt hasn't run yet.{' '}
                            {prompt.active
                                ? 'It runs in the next daily check.'
                                : 'Turn it on to include it in the daily check.'}
                        </p>
                    ) : (
                        <>
                            <ContentAutopilotStatStrip
                                className="grid-cols-1 @2xl/prompt-report:grid-cols-3"
                                data-attr="content-autopilot-prompt-kpis"
                            >
                                <ContentAutopilotKpiStat
                                    label="Mentioned in answers"
                                    description="Share of answers that name your brand, with or without a link. An answer that cites your site always counts as a mention."
                                    {...rateKpiCard(reportKpis.visibility)}
                                    onClick={() => showMetric('mentioned')}
                                    data-attr="content-autopilot-prompt-kpi-mentioned"
                                />
                                <ContentAutopilotKpiStat
                                    label="Cited as a source"
                                    description="Share of answers that link to a page on your site as a source, so people can click through to it."
                                    {...rateKpiCard(reportKpis.citation)}
                                    onClick={() => showMetric('cited')}
                                    data-attr="content-autopilot-prompt-kpi-cited"
                                />
                                <ContentAutopilotKpiStat
                                    label="Average position"
                                    description={POSITION_DESCRIPTION}
                                    {...positionKpiCard(reportKpis.position)}
                                    data-attr="content-autopilot-prompt-kpi-position"
                                />
                            </ContentAutopilotStatStrip>

                            <LemonTabs
                                activeKey={reportTab}
                                onChange={setReportTab}
                                data-attr="content-autopilot-prompt-tabs"
                                tabs={[
                                    {
                                        key: 'overview',
                                        label: 'Overview',
                                        content: (
                                            <ContentAutopilotPromptOverview
                                                stats={stats}
                                                kpis={reportKpis}
                                                chart={visibilityChart}
                                                metric={visibilityMetric}
                                                onMetricChange={setVisibilityMetric}
                                                query={visibilityQuery}
                                                consensus={consensusMatrix}
                                                sentiment={sentimentSummary}
                                                onOpenTab={setReportTab}
                                            />
                                        ),
                                    },
                                    {
                                        key: 'answers',
                                        label: 'Answers',
                                        content: <ContentAutopilotPromptAnswer />,
                                    },
                                    {
                                        key: 'sources',
                                        label: 'Sources',
                                        content: (
                                            <div className="flex flex-col gap-6">
                                                <div className="grid grid-cols-1 @3xl/prompt-report:grid-cols-2 gap-4">
                                                    <ContentAutopilotPromptQueryTile
                                                        title="Sites the engines cite for this prompt"
                                                        query={sourcesQuery}
                                                        uniqueKey={`aeo-prompt-sources-${promptId}`}
                                                        context={promptSourcesContext}
                                                        data-attr="content-autopilot-prompt-sources-tile"
                                                    />
                                                    <ContentAutopilotPromptQueryTile
                                                        title="Pages the engines cite most"
                                                        query={citationsQuery}
                                                        uniqueKey={`aeo-prompt-citations-${promptId}`}
                                                        context={promptCitationsContext}
                                                        data-attr="content-autopilot-prompt-citations-tile"
                                                    />
                                                </div>
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'sentiment',
                                        label: 'Sentiment',
                                        content: (
                                            <TabSection
                                                title="How the answers speak about you"
                                                description="Scored on the sentences that name you, so praise of another tool doesn't count."
                                            >
                                                <ContentAutopilotPromptSentiment
                                                    summary={sentimentSummary}
                                                    query={sentimentQuery}
                                                />
                                            </TabSection>
                                        ),
                                    },
                                    {
                                        key: 'searches',
                                        label: 'Searches',
                                        content: (
                                            <ContentAutopilotPromptQueryTile
                                                title="Searches the engines ran before answering"
                                                query={searchesQuery}
                                                uniqueKey={`aeo-prompt-searches-${promptId}`}
                                                context={promptSearchesContext}
                                                description="Engines that don't report their searches are left out."
                                                data-attr="content-autopilot-prompt-searches-tile"
                                            />
                                        ),
                                    },
                                    {
                                        key: 'history',
                                        label: 'History',
                                        content: (
                                            <div className="flex flex-col gap-6">
                                                {prompt.version_count > 1 ? (
                                                    <TabSection title="Versions">
                                                        <ContentAutopilotPromptVersions promptId={prompt.id} />
                                                    </TabSection>
                                                ) : null}
                                                <TabSection
                                                    title="All checks"
                                                    description="Pick a check to read its answer."
                                                >
                                                    <ContentAutopilotPromptChecks />
                                                </TabSection>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </>
                    )}
                </div>
            )}
            <ContentAutopilotPromptEditModal />
        </div>
    )
}
