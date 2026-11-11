import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotDraftButton } from './ContentAutopilotDraftButton'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptAnswer } from './ContentAutopilotPromptAnswer'
import { ContentAutopilotPromptArchiveBanner } from './ContentAutopilotPromptArchiveBanner'
import { ContentAutopilotPromptChecks } from './ContentAutopilotPromptChecks'
import { ContentAutopilotPromptConsensus } from './ContentAutopilotPromptConsensus'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptEditModal } from './ContentAutopilotPromptEditModal'
import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotPromptSentiment } from './ContentAutopilotPromptSentiment'
import { ContentAutopilotPromptVersions } from './ContentAutopilotPromptVersions'
import { POSITION_DESCRIPTION, positionKpiCard, rateKpiCard } from './promptReport'
import { promptCitationsContext, promptSearchesContext, promptSourcesContext } from './promptReportColumns'
import { draftableOpportunity } from './utils'

const Section = ({
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
            <h4 className="m-0">{title}</h4>
            {description ? <p className="m-0 text-xs text-muted">{description}</p> : null}
        </div>
        {children}
    </section>
)

const PromptPage = ({
    title,
    onBack,
    children,
}: {
    title: string
    onBack: () => void
    children: React.ReactNode
}): JSX.Element => (
    <div className="flex flex-col gap-4" data-attr="content-autopilot-prompt-page">
        <div>
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconArrowLeft />}
                onClick={onBack}
                data-attr="content-autopilot-prompt-back"
            >
                All prompts
            </LemonButton>
        </div>
        <h2 className="m-0">{title}</h2>
        {children}
    </div>
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
        consensusMatrix,
        sentimentSummary,
        visibilityMetric,
        visibilityQuery,
        sourcesQuery,
        citationsQuery,
        searchesQuery,
        sentimentQuery,
    } = useValues(contentAutopilotPromptDetailLogic)
    const { closePromptDetail, openPromptDetail, setArchiveConfirming, setPromptEditing, setVisibilityMetric } =
        useActions(contentAutopilotPromptDetailLogic)
    const { opportunityByPromptId } = useValues(contentAutopilotLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const draftOpportunity = prompt ? draftableOpportunity(opportunityByPromptId, prompt) : null

    if (!promptId) {
        return null
    }

    if (detailError === 'not_found') {
        return (
            <PromptPage title="Prompt not found" onBack={() => setWorkspaceTab('prompts')}>
                <p className="m-0">This prompt isn't in the project's prompt set anymore, or the link is wrong.</p>
            </PromptPage>
        )
    }

    const reportReady =
        prompt &&
        stats &&
        reportKpis &&
        consensusMatrix &&
        sentimentSummary &&
        visibilityQuery &&
        sourcesQuery &&
        citationsQuery &&
        searchesQuery &&
        sentimentQuery

    return (
        <PromptPage title={prompt?.prompt ?? 'Loading prompt'} onBack={() => setWorkspaceTab('prompts')}>
            {detailError === 'failed' ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => openPromptDetail(promptId) }}>
                    Couldn't load this prompt. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !reportReady ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-8 w-1/2" />
                    <LemonSkeleton className="h-24 w-full" />
                    <LemonSkeleton className="h-40 w-full" />
                </div>
            ) : (
                <div className="@container/prompt-report flex flex-col gap-6">
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
                        <span className="text-muted">
                            Last checked {lastCheckedAt ? <TZLabel time={lastCheckedAt} /> : 'never'}
                        </span>
                        <span className="text-muted">{pluralize(stats.total_checks, 'check')} in total</span>
                        {prompt.archived_at ? null : (
                            <div className="ml-auto flex gap-2">
                                {draftOpportunity ? (
                                    <ContentAutopilotDraftButton
                                        opportunity={draftOpportunity}
                                        onReview={closePromptDetail}
                                    />
                                ) : null}
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => setPromptEditing(true)}
                                    data-attr="content-autopilot-prompt-edit"
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    onClick={() => setArchiveConfirming(true)}
                                    disabledReason={archiveConfirming ? 'Confirm or cancel below' : undefined}
                                    data-attr="content-autopilot-prompt-archive"
                                >
                                    Archive
                                </LemonButton>
                            </div>
                        )}
                    </div>
                    <ContentAutopilotPromptArchiveBanner />
                    {prompt.version_count > 1 ? (
                        <Section title="Versions">
                            <ContentAutopilotPromptVersions promptId={prompt.id} />
                        </Section>
                    ) : null}

                    {stats.engines.length === 0 ? (
                        <p className="m-0 text-muted">
                            This prompt hasn't run yet.{' '}
                            {prompt.active
                                ? 'It runs in the next daily check.'
                                : 'Turn it on to include it in the daily check.'}
                        </p>
                    ) : (
                        <>
                            <Section
                                title="Last 30 days, all engines"
                                description={`${pluralize(reportKpis.answers, 'answer')} across ${pluralize(reportKpis.days, 'day')}.`}
                            >
                                <div className="grid grid-cols-1 @2xl/prompt-report:grid-cols-3 gap-3">
                                    <ContentAutopilotPromptKpiCard
                                        label="Mentioned in answers"
                                        description="Share of answers that name your brand, with or without a link. An answer that cites your site always counts as a mention."
                                        {...rateKpiCard(reportKpis.visibility)}
                                        data-attr="content-autopilot-prompt-kpi-mentioned"
                                    />
                                    <ContentAutopilotPromptKpiCard
                                        label="Cited as a source"
                                        description="Share of answers that link to a page on your site as a source, so people can click through to it."
                                        {...rateKpiCard(reportKpis.citation)}
                                        data-attr="content-autopilot-prompt-kpi-cited"
                                    />
                                    <ContentAutopilotPromptKpiCard
                                        label="Average position"
                                        description={POSITION_DESCRIPTION}
                                        {...positionKpiCard(reportKpis.position)}
                                        data-attr="content-autopilot-prompt-kpi-position"
                                    />
                                </div>
                            </Section>

                            <Section
                                title="Mentions and citations over time"
                                description="One line per engine, one point per day it ran."
                            >
                                <ContentAutopilotPromptQueryTile
                                    title={
                                        visibilityMetric === 'cited'
                                            ? 'Share of answers that cite you'
                                            : 'Share of answers that mention you'
                                    }
                                    query={visibilityQuery}
                                    uniqueKey={`aeo-prompt-visibility-${promptId}-${visibilityMetric}`}
                                    bodyClassName="h-72 p-2"
                                    actions={
                                        <LemonSegmentedButton
                                            size="xsmall"
                                            value={visibilityMetric}
                                            onChange={setVisibilityMetric}
                                            options={[
                                                { value: 'cited', label: 'Cited' },
                                                { value: 'mentioned', label: 'Mentioned' },
                                            ]}
                                            data-attr="content-autopilot-prompt-visibility-metric"
                                        />
                                    }
                                    data-attr="content-autopilot-prompt-visibility-tile"
                                />
                            </Section>

                            <Section title="Answers" description="The latest answer from each engine.">
                                <ContentAutopilotPromptAnswer />
                            </Section>

                            <Section
                                title="Cited sources"
                                description="The sites and pages the engines link to when they answer this prompt."
                            >
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
                            </Section>

                            <Section
                                title="Cited sites by engine"
                                description="The share of each engine's answers that link to a site. A darker cell means the engine links to that site more often."
                            >
                                <ContentAutopilotPromptConsensus matrix={consensusMatrix} />
                            </Section>

                            <Section
                                title="Sentiment"
                                description="Scored on the sentences that name you, so praise of another tool does not count."
                            >
                                <ContentAutopilotPromptSentiment summary={sentimentSummary} query={sentimentQuery} />
                            </Section>

                            <Section
                                title="Engine searches"
                                description="The searches an engine ran before it answered. Engines that do not report their searches are left out."
                            >
                                <ContentAutopilotPromptQueryTile
                                    title="Searches"
                                    query={searchesQuery}
                                    uniqueKey={`aeo-prompt-searches-${promptId}`}
                                    context={promptSearchesContext}
                                    footer={
                                        stats.top_words.length ? (
                                            <span className="flex flex-wrap items-center gap-1">
                                                <span className="mr-1">Most common words in those searches:</span>
                                                {stats.top_words.map((word) => (
                                                    <LemonTag key={word.word} size="small">
                                                        {word.word} <span className="text-muted">{word.count}</span>
                                                    </LemonTag>
                                                ))}
                                            </span>
                                        ) : undefined
                                    }
                                    data-attr="content-autopilot-prompt-searches-tile"
                                />
                            </Section>

                            <Section title="All checks">
                                <ContentAutopilotPromptChecks />
                            </Section>
                        </>
                    )}
                </div>
            )}
            <ContentAutopilotPromptEditModal />
        </PromptPage>
    )
}
