import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSegmentedButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptAnswer } from './ContentAutopilotPromptAnswer'
import { ContentAutopilotPromptArchiveBanner } from './ContentAutopilotPromptArchiveBanner'
import { ContentAutopilotPromptChecks } from './ContentAutopilotPromptChecks'
import { ContentAutopilotPromptConsensus } from './ContentAutopilotPromptConsensus'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotPromptSentiment } from './ContentAutopilotPromptSentiment'
import { ContentAutopilotPromptVersions } from './ContentAutopilotPromptVersions'
import { promptCitationsContext, promptSearchesContext, promptSourcesContext } from './promptReportColumns'

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
    const { closePromptDetail, openPromptDetail, setArchiveConfirming, setVisibilityMetric } = useActions(
        contentAutopilotPromptDetailLogic
    )

    if (!promptId) {
        return null
    }

    if (detailError === 'not_found') {
        return (
            <LemonModal isOpen onClose={closePromptDetail} title="Prompt not found" width={640}>
                <p className="m-0">
                    This prompt isn't in the project's prompt set anymore. Close this and refresh the list.
                </p>
            </LemonModal>
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
        <LemonModal isOpen onClose={closePromptDetail} title={prompt?.prompt ?? 'Loading prompt'} width={960}>
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
                            <LemonButton
                                size="small"
                                type="secondary"
                                status="danger"
                                className="ml-auto"
                                onClick={() => setArchiveConfirming(true)}
                                disabledReason={archiveConfirming ? 'Confirm or cancel below' : undefined}
                                data-attr="content-autopilot-prompt-archive"
                            >
                                Archive
                            </LemonButton>
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
                                <div className="grid grid-cols-1 @2xl/prompt-report:grid-cols-2 gap-3">
                                    <ContentAutopilotPromptKpiCard
                                        label="Mentioned in answers"
                                        description="Share of answers that name you. An answer that cites your site always counts."
                                        kpi={reportKpis.visibility}
                                        data-attr="content-autopilot-prompt-kpi-mentioned"
                                    />
                                    <ContentAutopilotPromptKpiCard
                                        label="Cited as a source"
                                        description="Share of answers that link to a page on your site."
                                        kpi={reportKpis.citation}
                                        data-attr="content-autopilot-prompt-kpi-cited"
                                    />
                                </div>
                            </Section>

                            <Section
                                title="How often engines mention or cite you"
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
                                title="Where the answers come from"
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
                                title="Which sites each engine relies on"
                                description="The share of each engine's answers that link to a site. A darker cell means the engine links to that site more often."
                            >
                                <ContentAutopilotPromptConsensus matrix={consensusMatrix} />
                            </Section>

                            <Section
                                title="How answers talk about you"
                                description="Scored on the sentences that name you, so praise of another tool does not count."
                            >
                                <ContentAutopilotPromptSentiment summary={sentimentSummary} query={sentimentQuery} />
                            </Section>

                            <Section
                                title="What the engines searched for"
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
        </LemonModal>
    )
}
