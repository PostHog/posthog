import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPageHeader } from './ContentAutopilotPageHeader'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptAnswer } from './ContentAutopilotPromptAnswer'
import { ContentAutopilotPromptArchiveBanner } from './ContentAutopilotPromptArchiveBanner'
import { ContentAutopilotPromptChecks } from './ContentAutopilotPromptChecks'
import { type PromptReportTab, contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptDetailSkeleton } from './ContentAutopilotPromptDetailSkeleton'
import { ContentAutopilotPromptEditModal } from './ContentAutopilotPromptEditModal'
import { ContentAutopilotPromptOverview } from './ContentAutopilotPromptOverview'
import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import { ContentAutopilotPromptSentiment } from './ContentAutopilotPromptSentiment'
import { ContentAutopilotPromptVersions } from './ContentAutopilotPromptVersions'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { POSITION_DESCRIPTION, positionKpiCard, rateKpiCard } from './promptReport'
import { promptCitationsContext, promptSearchesContext, promptSourcesContext } from './promptReportColumns'

const REPORT_TABS: { key: PromptReportTab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'answers', label: 'Answers' },
    { key: 'sources', label: 'Sources' },
    { key: 'sentiment', label: 'Sentiment' },
    { key: 'searches', label: 'Searches' },
    { key: 'history', label: 'History' },
]

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
        <div className="flex flex-col gap-1">
            <Heading size="sm" render={<h3 className="m-0" />}>
                {title}
            </Heading>
            {description ? (
                <Text size="xs" variant="muted" className="m-0">
                    {description}
                </Text>
            ) : null}
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
    const { openPromptDetail, setArchiveConfirming, setPromptEditing, setReportTab, setVisibilityMetric } = useActions(
        contentAutopilotPromptDetailLogic
    )
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
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
                <Text size="xs" className="m-0">
                    This prompt isn't in the project's prompt set anymore, or the link is wrong.
                </Text>
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
                <Button
                    variant="outline"
                    onClick={() => setPromptEditing(true)}
                    data-attr="content-autopilot-prompt-edit"
                >
                    Edit
                </Button>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="More actions"
                                tooltip="More actions"
                                data-attr="content-autopilot-prompt-more"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem
                            onClick={() => void copyToClipboard(window.location.href, 'link to this prompt')}
                        >
                            Copy link to this prompt
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setArchiveConfirming(true)}
                            disabledReason={archiveConfirming ? 'Confirm or cancel below' : undefined}
                            data-attr="content-autopilot-prompt-archive"
                        >
                            Archive
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </>
        ) : null

    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-prompt-page">
            <ContentAutopilotPageHeader
                title={prompt?.prompt ?? (detailError === 'failed' ? 'Prompt' : 'Loading prompt')}
                backLabel="Prompts"
                backDataAttr="content-autopilot-prompt-back"
                onBack={backToPrompts}
                actions={actions}
            />
            {detailError === 'failed' ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => openPromptDetail(promptId) }}
                >
                    Couldn't load this prompt. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : !reportReady ? (
                <ContentAutopilotPromptDetailSkeleton />
            ) : (
                <div className="@container/prompt-report flex flex-col gap-4">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                        {prompt.topic ? (
                            <AiVisibilityTag>{prompt.topic}</AiVisibilityTag>
                        ) : (
                            <AiVisibilityTag type="muted">No topic</AiVisibilityTag>
                        )}
                        <AiVisibilityTag type="muted">Version {prompt.current_version}</AiVisibilityTag>
                        {prompt.archived_at ? (
                            <AiVisibilityTag type="muted">Archived</AiVisibilityTag>
                        ) : (
                            <ContentAutopilotPromptActiveSwitch
                                promptId={prompt.id}
                                active={prompt.active}
                                label="Active"
                            />
                        )}
                        <Text size="xs" variant="muted" render={<span />}>
                            Last checked {lastCheckedAt ? <TZLabel time={lastCheckedAt} /> : 'never'}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            {pluralize(stats.total_checks, 'check')} in total
                        </Text>
                    </div>
                    <ContentAutopilotPromptArchiveBanner />

                    {stats.engines.length === 0 ? (
                        <Empty data-attr="content-autopilot-prompt-no-checks">
                            <EmptyHeader>
                                <EmptyTitle>This prompt hasn't run yet</EmptyTitle>
                                <EmptyDescription>
                                    {prompt.active
                                        ? 'It runs in the next daily check.'
                                        : 'Turn it on to include it in the daily check.'}
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <>
                            <ContentAutopilotStatStrip
                                className="grid-cols-1 @2xl/prompt-report:grid-cols-3"
                                data-attr="content-autopilot-prompt-kpis"
                            >
                                <ContentAutopilotKpiStat
                                    label="Visibility"
                                    description="Share of answers that name your brand or link to your site."
                                    {...rateKpiCard(reportKpis.visibility)}
                                    onClick={() => showMetric('mentioned')}
                                    data-attr="content-autopilot-prompt-kpi-mentioned"
                                />
                                <ContentAutopilotKpiStat
                                    label="Cited as a source"
                                    description="Share of answers that link to a page on your site."
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

                            <Tabs
                                value={reportTab}
                                onValueChange={(tab: PromptReportTab) => setReportTab(tab)}
                                data-attr="content-autopilot-prompt-tabs"
                            >
                                <div className="overflow-x-auto">
                                    <TabsList variant="line">
                                        {REPORT_TABS.map(({ key, label }) => (
                                            <TabsTrigger key={key} value={key}>
                                                {label}
                                            </TabsTrigger>
                                        ))}
                                    </TabsList>
                                </div>
                                <TabsContent value="overview">
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
                                </TabsContent>
                                <TabsContent value="answers">
                                    <ContentAutopilotPromptAnswer />
                                </TabsContent>
                                <TabsContent value="sources">
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
                                </TabsContent>
                                <TabsContent value="sentiment">
                                    <TabSection
                                        title="How the answers speak about you"
                                        description="Scored on the sentences that name you, so praise of another tool doesn't count."
                                    >
                                        <ContentAutopilotPromptSentiment
                                            summary={sentimentSummary}
                                            query={sentimentQuery}
                                        />
                                    </TabSection>
                                </TabsContent>
                                <TabsContent value="searches">
                                    <ContentAutopilotPromptQueryTile
                                        title="Searches the engines ran before answering"
                                        query={searchesQuery}
                                        uniqueKey={`aeo-prompt-searches-${promptId}`}
                                        context={promptSearchesContext}
                                        description="Engines that don't report their searches are left out."
                                        data-attr="content-autopilot-prompt-searches-tile"
                                    />
                                </TabsContent>
                                <TabsContent value="history">
                                    <div className="flex flex-col gap-6">
                                        {prompt.version_count > 1 ? (
                                            <TabSection title="Versions">
                                                <ContentAutopilotPromptVersions promptId={prompt.id} />
                                            </TabSection>
                                        ) : null}
                                        <TabSection title="All checks">
                                            <ContentAutopilotPromptChecks />
                                        </TabSection>
                                    </div>
                                </TabsContent>
                            </Tabs>
                        </>
                    )}
                </div>
            )}
            <ContentAutopilotPromptEditModal />
        </div>
    )
}
