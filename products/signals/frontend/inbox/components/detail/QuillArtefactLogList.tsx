import { Fragment, useState } from 'react'

import { IconComment, IconCopy, IconExternal, IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { CodeLine, Language } from 'lib/components/CodeSnippet'
import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { Task } from 'products/posthog_ai/frontend/types/taskTypes'
import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import { rankingScoreForHead } from '../../filterOptions'
import { QuillSignalCard } from '../../QuillSignalCard'
import { EnrichedReviewer, SignalReportArtefact } from '../../types'
import { prettifyScoutSkillName } from '../../utils/scoutRunsWindow'
import { QuillSignalReportActionabilityBadge } from '../badges/QuillSignalReportActionabilityBadge'
import { formatRankingLift, formatRankingProbability } from '../cards/rankingFormat'
import { RankingLiftBar } from '../cards/RankingLiftBar'
import { SignalCardDisclosureProvider } from '../signalCards/SignalCardShell'
import {
    artefactBodyHasOwnCard,
    artefactFindingSignal,
    artefactMarkerIcon,
    artefactPullRequestContext,
    type ArtefactPullRequestOutcome,
    artefactSummary,
    codeReviewLinks,
    languageFromPath,
    orderArtefactLog,
    prettify,
    reviewerDisplayName,
    splitRankingHeads,
} from './artefactLogPresentation'
import {
    artefactAttributionLabel,
    artefactLocationLabel,
    AUTOSTART_SKIP_REASON_LABELS,
    AutostartSkipContent,
    CheckObservationContent,
    CheckResultContent,
    CheckScheduledContent,
    CodeReferenceContent,
    CodeReviewContent,
    CommitContent,
    DismissalContent,
    ImplementationDecisionContent,
    ImplementationHandoverContent,
    ImplementationReplacementContent,
    LineReferenceContent,
    NoteContent,
    ScoutNoteLeftContent,
    RankingHead,
    RankingModel,
    RankingScoreView,
    readRankingScore,
    RelatedToContent,
    REPORT_LINK_KIND_LABELS,
    ReportLinkContent,
    RepoSelectionContent,
    SummaryChangeContent,
    TaskRunArtefactContent,
    TitleChangeContent,
} from './artefactTypes'
import { prActivityTitle } from './prActivityPresentation'
import { QuillActivityNoteQuote } from './QuillActivityNoteQuote'
import { QuillArtefactCommit } from './QuillArtefactCommit'
import { QuillArtefactPullRequest } from './QuillArtefactPullRequest'
import { QuillArtefactTaskRun } from './QuillArtefactTaskRun'
import { quillBadgeVariant } from './quillBadgeVariant'
import { QuillCheckObservationBody } from './QuillCheckObservationBody'
import { CHECK_LIFECYCLE_ENTRIES, inconclusiveReasonLabel } from './reportCheckPresentation'

/** A short relevance / context note above a code block. */
function QuillRelevanceNote({ note }: { note?: string }): JSX.Element | null {
    if (!note?.trim()) {
        return null
    }
    return (
        <Text size="xs" variant="muted" render={<span />} className="block">
            {note}
        </Text>
    )
}

/** A read-only highlighted code block sized for the activity log. */
function QuillCodeRefBlock({ code, language }: { code: string; language: Language }): JSX.Element {
    return (
        <div className="relative rounded-md border border-border bg-muted py-1.5 ps-2 pe-8 text-xs">
            <CodeLine text={code} language={language} wrapLines />
            <Button
                size="icon-xs"
                aria-label="Copy to clipboard"
                tooltip="Copy to clipboard"
                data-attr="copy-code-button"
                className="absolute end-1 top-1"
                onClick={(e) => {
                    e.stopPropagation()
                    void copyToClipboard(code, 'snippet')
                }}
            >
                <IconCopy />
            </Button>
        </div>
    )
}

function QuillActivityBodyCard({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Card size="sm" className="w-full">
            <CardContent className="min-w-0">{children}</CardContent>
        </Card>
    )
}

function QuillReasoningBody({ text }: { text: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="m-0 leading-relaxed">
            {text}
        </Text>
    )
}

/** An inline link to another page in the app, at the size of the text around it. */
function QuillInlineLink({
    to,
    dataAttr,
    children,
}: {
    to: string
    dataAttr?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Button variant="link" size="inline" render={<LinkPrimitive to={to} />} data-attr={dataAttr}>
            {children}
            <IconExternal className="size-3" />
        </Button>
    )
}

function QuillLogDisclosure({
    label,
    defaultOpen = false,
    children,
}: {
    label: string
    defaultOpen?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <Collapsible defaultOpen={defaultOpen} className="flex min-w-0 flex-col gap-1">
            <CollapsibleTrigger className="-ms-2 self-start font-normal text-muted-foreground">
                {label}
            </CollapsibleTrigger>
            <CollapsibleContent className="ps-3">{children}</CollapsibleContent>
        </Collapsible>
    )
}

function QuillNoteBody({ note, author }: { note: string; author?: string }): JSX.Element {
    return (
        <div className="flex w-full flex-col gap-1">
            <LemonMarkdown className="text-xs leading-normal text-muted-foreground" disableImages>
                {note}
            </LemonMarkdown>
            {author?.trim() ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    By {author}
                </Text>
            ) : null}
        </div>
    )
}

function QuillContentChangeBody({
    previous,
    current,
    markdown = false,
}: {
    previous?: string | null
    current: string
    markdown?: boolean
}): JSX.Element {
    const renderText = (text: string, muted: boolean): JSX.Element => {
        const color = muted ? 'text-muted-foreground' : 'text-foreground'
        return markdown ? (
            <LemonMarkdown className={cn('text-xs leading-normal', color)} disableImages>
                {text}
            </LemonMarkdown>
        ) : (
            <Text size="xs" render={<span />} className={color}>
                {text}
            </Text>
        )
    }

    return (
        <div className="flex w-full min-w-0 flex-col gap-2">
            <div className="min-w-0">{renderText(current, false)}</div>
            {previous?.trim() ? (
                <div className="flex flex-col gap-0.5 border-s border-border ps-2">
                    <Text size="xs" weight="medium" render={<span />} className="text-subtle-foreground">
                        Previous
                    </Text>
                    {renderText(previous, true)}
                </div>
            ) : null}
        </div>
    )
}

function QuillReviewersBody({ reviewers }: { reviewers: EnrichedReviewer[] }): JSX.Element {
    if (reviewers.length === 0) {
        return (
            <Text size="xs" render={<span />} className="text-subtle-foreground">
                No reviewers assigned.
            </Text>
        )
    }
    return (
        <div className="flex flex-wrap gap-1.5">
            {reviewers.map((reviewer) => {
                const name = reviewerDisplayName(reviewer)
                const body = (
                    <>
                        <QuillPersonAvatar name={name} email={reviewer.user?.email} size="xs" />
                        <span className="text-foreground">{name}</span>
                        {reviewer.github_login ? (
                            <span className="font-mono text-subtle-foreground">@{reviewer.github_login}</span>
                        ) : null}
                    </>
                )
                return reviewer.github_login ? (
                    <LinkPrimitive
                        key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}
                        to={`https://github.com/${reviewer.github_login}`}
                        target="_blank"
                        disableClientSideRouting
                        className="inline-flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-fill-hover"
                    >
                        {body}
                        <IconExternal className="size-3 shrink-0 text-subtle-foreground" />
                    </LinkPrimitive>
                ) : (
                    <div
                        key={reviewer.user?.uuid ?? reviewer.user_uuid ?? name}
                        className="inline-flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-xs"
                    >
                        {body}
                    </div>
                )
            })}
        </div>
    )
}

function QuillRepoSelectionBody({ content }: { content: RepoSelectionContent }): JSX.Element | null {
    if (!content.reason?.trim()) {
        return null
    }
    return <QuillReasoningBody text={content.reason} />
}

function QuillSignalFindingBody({ signal }: { signal: SignalNode }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="w-full">
            <SignalCardDisclosureProvider expanded={expanded} onChange={setExpanded}>
                <QuillSignalCard signal={signal} />
            </SignalCardDisclosureProvider>
        </div>
    )
}

function QuillRelatedReportBody({ content }: { content: RelatedToContent }): JSX.Element | null {
    if (!content.report_id) {
        return null
    }
    return (
        <Text size="xs" render={<span />}>
            <QuillInlineLink to={urls.inboxReport('reports', content.report_id)}>Open report</QuillInlineLink>
        </Text>
    )
}

function QuillReportLinkBody({ content }: { content: ReportLinkContent }): JSX.Element | null {
    if (!content.report_id) {
        return null
    }
    const kind = content.kind ? (REPORT_LINK_KIND_LABELS[content.kind] ?? content.kind) : null
    return (
        <div className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-2">
                {kind ? <Badge>{kind}</Badge> : null}
                <QuillInlineLink
                    to={urls.inboxReport('reports', content.report_id)}
                    dataAttr="artefact-report-link-open"
                >
                    Open report
                </QuillInlineLink>
            </div>
            {content.reason?.trim() ? <QuillReasoningBody text={content.reason} /> : null}
        </div>
    )
}

function QuillAutostartSkipBody({ content }: { content: AutostartSkipContent }): JSX.Element | null {
    if (!content.detail?.trim()) {
        return null
    }
    const reason = content.skip_reason
        ? (AUTOSTART_SKIP_REASON_LABELS[content.skip_reason] ?? prettify(content.skip_reason))
        : null
    return (
        <div className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-2">
                {reason ? <Badge>{reason}</Badge> : null}
                {content.linked_report_id ? (
                    <QuillInlineLink
                        to={urls.inboxReport('reports', content.linked_report_id)}
                        dataAttr="artefact-autostart-skip-open"
                    >
                        Open that report
                    </QuillInlineLink>
                ) : null}
            </div>
            <QuillReasoningBody text={content.detail} />
        </div>
    )
}

function QuillCheckResultBody({ content }: { content: CheckResultContent }): JSX.Element | null {
    if (!content.explanation?.trim()) {
        return null
    }
    return (
        <div className="flex w-full flex-col items-start gap-1">
            <Text size="xs" render={<span />}>
                {content.explanation}
            </Text>
            {content.outcome === 'inconclusive' ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    {inconclusiveReasonLabel(content.reason)}
                </Text>
            ) : null}
            {content.threshold ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    Expected {content.threshold}
                    {typeof content.baseline_value === 'number' ? `, was ${content.baseline_value} when set` : ''}
                </Text>
            ) : null}
        </div>
    )
}

/** Shares a shape with `QuillCheckResultBody`, so one check reads as the same thing across its entries. */
function QuillCheckLifecycleBody({
    title,
    rationale,
    detail,
}: {
    title?: string
    rationale?: string
    detail: string
}): JSX.Element {
    return (
        <div className="flex w-full flex-col items-start gap-1">
            {title?.trim() ? (
                <Text size="xs" render={<span />}>
                    {title}
                </Text>
            ) : null}
            {rationale?.trim() ? (
                <Text size="xs" render={<span />}>
                    {rationale}
                </Text>
            ) : null}
            {detail ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    {detail}
                </Text>
            ) : null}
        </div>
    )
}

function QuillCodeReviewBody({ content }: { content: CodeReviewContent }): JSX.Element | null {
    const counts = content.counts
    const { reviewUrl, repository } = codeReviewLinks(content)
    const hasContent = content.repository || counts || reviewUrl

    if (!hasContent) {
        return null
    }

    return (
        <div className="flex w-full flex-col items-start gap-1.5">
            <div className="flex flex-wrap items-center gap-1">
                {(counts?.must_fix ?? 0) > 0 ? <Badge variant="destructive">{counts?.must_fix} must fix</Badge> : null}
                {(counts?.should_fix ?? 0) > 0 ? (
                    <Badge variant="warning">{counts?.should_fix} should fix</Badge>
                ) : null}
                {(counts?.consider ?? 0) > 0 ? <Badge>{counts?.consider} consider</Badge> : null}
            </div>
            {repository ? (
                <Text size="xs" render={<span />} className="break-all font-mono text-subtle-foreground">
                    {repository}
                </Text>
            ) : null}
            {reviewUrl ? (
                <Text size="xs" render={<span />}>
                    <Button
                        variant="link"
                        size="inline"
                        render={<LinkPrimitive to={reviewUrl} target="_blank" disableClientSideRouting />}
                    >
                        View review
                        <IconExternal className="size-3" />
                    </Button>
                </Text>
            ) : null}
        </div>
    )
}

const NO_HOLDOUT_READ = 'No holdout read for this head yet'

function QuillRankingHeadRows({ heads }: { heads: RankingHead[] }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            {heads.map((head) => {
                const tone = head.readable ? 'text-foreground' : 'text-subtle-foreground'
                const score = rankingScoreForHead(head.name)
                return (
                    <div key={head.name} className="flex min-w-0 items-center gap-2">
                        {score ? (
                            <Tooltip>
                                <TooltipTrigger render={<span className={cn('w-24 shrink truncate', tone)} />}>
                                    {score.name}
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">{score.description}</TooltipContent>
                            </Tooltip>
                        ) : (
                            <span className={cn('w-24 shrink truncate', tone)}>{prettify(head.name)}</span>
                        )}
                        <span className="min-w-8 max-w-40 flex-1">
                            <RankingLiftBar
                                lift={head.lift}
                                className={head.readable ? 'bg-primary' : 'bg-muted-foreground'}
                            />
                        </span>
                        <span className={cn('w-12 shrink-0 text-end tabular-nums', tone)}>
                            {head.lift !== null ? formatRankingLift(head.lift) : null}
                        </span>
                        <span className="inline-flex w-14 shrink-0 items-center justify-end gap-1 tabular-nums text-subtle-foreground">
                            {formatRankingProbability(head.probability)}
                            {head.readable ? (
                                <span className="size-3" aria-hidden />
                            ) : (
                                <Tooltip>
                                    <TooltipTrigger render={<span className="inline-flex" />}>
                                        <IconInfo className="size-3" aria-label={NO_HOLDOUT_READ} />
                                    </TooltipTrigger>
                                    <TooltipContent>{NO_HOLDOUT_READ}</TooltipContent>
                                </Tooltip>
                            )}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}

function QuillRankingHeads({ heads }: { heads: RankingHead[] }): JSX.Element {
    const { scoreHeads, otherHeads } = splitRankingHeads(heads)
    return (
        <div className="flex min-w-0 flex-col gap-1">
            {scoreHeads.length > 0 ? <QuillRankingHeadRows heads={scoreHeads} /> : null}
            {otherHeads.length > 0 ? (
                <QuillLogDisclosure label={`Other heads (${otherHeads.length})`}>
                    <QuillRankingHeadRows heads={otherHeads} />
                </QuillLogDisclosure>
            ) : null}
        </div>
    )
}

function QuillRankingModelResult({ model }: { model: RankingModel }): JSX.Element {
    return model.status === 'skipped' || model.heads.length === 0 ? (
        <span className="text-subtle-foreground">Skipped{model.skipReason ? `: ${model.skipReason}` : ''}</span>
    ) : (
        <QuillRankingHeads heads={model.heads} />
    )
}

function QuillRankingScoreBody({ score }: { score: RankingScoreView }): JSX.Element {
    return (
        <div className="flex w-full min-w-0 flex-col gap-2 text-xs">
            <QuillRankingModelResult model={score.served} />
            <span className="flex flex-wrap items-center gap-x-1 text-subtle-foreground">
                <span className="break-all font-mono">{score.served.key}</span>
                {score.manifestVersion ? <span>· manifest {score.manifestVersion}</span> : null}
                {score.scoredAt ? (
                    <span className="inline-flex items-center gap-1">
                        · <TZLabel time={score.scoredAt} />
                    </span>
                ) : null}
            </span>
            {score.challengers.length > 0 ? (
                <QuillLogDisclosure label={`Other models (${score.challengers.length})`}>
                    <div className="flex flex-col gap-3">
                        {score.challengers.map((model) => {
                            const role = model.roles.find((r) => r !== 'served')
                            return (
                                <div key={model.key} className="flex min-w-0 flex-col gap-1">
                                    <span className="flex flex-wrap items-center gap-1.5">
                                        <span className="break-all font-mono text-muted-foreground">{model.key}</span>
                                        {role ? <Badge>{prettify(role)}</Badge> : null}
                                    </span>
                                    <QuillRankingModelResult model={model} />
                                </div>
                            )
                        })}
                    </div>
                </QuillLogDisclosure>
            ) : null}
        </div>
    )
}

function renderQuillArtefactSummary(artefact: SignalReportArtefact, monitoringEnabled: boolean): JSX.Element | null {
    const summary = artefactSummary(artefact, monitoringEnabled)
    switch (summary?.kind) {
        case 'tag':
            return <Badge variant={quillBadgeVariant(summary.type)}>{summary.label}</Badge>
        case 'text':
            return (
                <Text size="xs" variant="muted" render={<span />} className={cn(summary.mono && 'font-mono')}>
                    {summary.text}
                </Text>
            )
        case 'actionability':
            return (
                <span className="inline-flex items-center gap-1">
                    <QuillSignalReportActionabilityBadge actionability={summary.actionability} />
                    {summary.alreadyAddressed ? <Badge variant="warning">Already addressed</Badge> : null}
                </span>
            )
        default:
            return null
    }
}

function renderQuillArtefactBody({
    monitoringEnabled,
    notesEnabled,
    reportId,
    artefact,
    knownTasks,
    knownPullRequests,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
    knownPullRequests: Map<string, SignalReportPullRequestApi>
    monitoringEnabled: boolean
    notesEnabled: boolean
}): JSX.Element | null {
    const content = artefact.content
    const renderPullRequest = (url: string, outcome?: ArtefactPullRequestOutcome): JSX.Element => (
        <QuillArtefactPullRequest
            key={url}
            url={url}
            {...artefactPullRequestContext(url, knownPullRequests, knownTasks)}
            outcome={outcome}
        />
    )

    switch (artefact.type) {
        case 'pull_request':
            return typeof content.url === 'string' && content.url ? renderPullRequest(content.url) : null
        case 'code_reference': {
            const c = content as CodeReferenceContent
            return (
                <div className="flex flex-col gap-1.5">
                    <QuillRelevanceNote note={c.relevance_note} />
                    {c.contents ? (
                        <QuillCodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} />
                    ) : null}
                </div>
            )
        }
        case 'line_reference': {
            const c = content as LineReferenceContent
            return (
                <div className="flex flex-col gap-1.5">
                    <QuillRelevanceNote note={c.note} />
                    {c.contents ? (
                        <QuillCodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} />
                    ) : null}
                </div>
            )
        }
        case 'commit':
            return (
                <QuillArtefactCommit reportId={reportId} artefactId={artefact.id} content={content as CommitContent} />
            )
        case 'task_run': {
            const c = content as TaskRunArtefactContent
            return <QuillArtefactTaskRun content={c} knownTask={knownTasks?.get(c.task_id) ?? null} />
        }
        case 'note': {
            const c = content as NoteContent
            if (notesEnabled && artefact.actor_kind === 'user') {
                return <QuillActivityNoteQuote reportId={reportId} text={c.note} />
            }
            return <QuillNoteBody note={c.note} author={c.author} />
        }
        case 'scout_note_left': {
            const c = content as ScoutNoteLeftContent
            if (notesEnabled) {
                return <QuillActivityNoteQuote reportId={reportId} text={c.note} scoutSkillName={c.skill_name} />
            }
            // Without the Notes list, the entry is the only place the note shows, so it reads as a note.
            return (
                <div className="flex w-full flex-col gap-1">
                    <QuillNoteBody note={c.note} />
                    <Text size="xs" render={<span />} className="text-subtle-foreground">
                        {c.skill_name?.trim() ? `For ${prettifyScoutSkillName(c.skill_name)}` : 'For every scout'}
                    </Text>
                </div>
            )
        }
        case 'priority_judgment':
        case 'actionability_judgment':
        case 'safety_judgment': {
            const c = content as { explanation?: string }
            return c.explanation ? <QuillReasoningBody text={c.explanation} /> : null
        }
        case 'signal_finding':
            return null
        case 'suggested_reviewers':
            return <QuillReviewersBody reviewers={(content as unknown as EnrichedReviewer[]) ?? []} />
        case 'repo_selection':
            return <QuillRepoSelectionBody content={content as RepoSelectionContent} />
        case 'related_to':
            return <QuillRelatedReportBody content={content as RelatedToContent} />
        case 'report_link':
            return <QuillReportLinkBody content={content as ReportLinkContent} />
        case 'autostart_skip':
            return <QuillAutostartSkipBody content={content as AutostartSkipContent} />
        case 'code_review':
            return <QuillCodeReviewBody content={content as CodeReviewContent} />
        case 'check_observation':
            return <QuillCheckObservationBody content={content as CheckObservationContent} />
        case 'check_result':
            return <QuillCheckResultBody content={content as CheckResultContent} />
        case 'check_scheduled':
        case 'check_expired':
        case 'check_cancelled': {
            const c = content as CheckScheduledContent
            return (
                <QuillCheckLifecycleBody
                    title={c.title}
                    rationale={c.rationale}
                    detail={CHECK_LIFECYCLE_ENTRIES[artefact.type](c, monitoringEnabled).detail}
                />
            )
        }
        case 'title_change': {
            const c = content as TitleChangeContent
            return <QuillContentChangeBody previous={c.old_title} current={c.new_title ?? ''} />
        }
        case 'summary_change': {
            const c = content as SummaryChangeContent
            return <QuillContentChangeBody previous={c.old_summary} current={c.new_summary ?? ''} markdown />
        }
        case 'dismissal': {
            const c = content as DismissalContent
            return c.note ? <QuillRelevanceNote note={c.note} /> : null
        }
        case 'implementation_decision': {
            const c = content as ImplementationDecisionContent
            return (
                <div className="flex flex-col gap-3 text-xs">
                    <QuillReasoningBody text={c.reason ?? ''} />
                    {(c.targets ?? []).map(({ pr_url }) => renderPullRequest(pr_url))}
                </div>
            )
        }
        case 'implementation_replacement': {
            const c = content as ImplementationReplacementContent
            return (
                <div className="flex flex-col gap-3 text-xs">
                    <QuillReasoningBody text="These PRs stay open while the replacement runs." />
                    {(c.decision?.targets ?? []).map(({ pr_url }) => renderPullRequest(pr_url))}
                </div>
            )
        }
        case 'implementation_handover': {
            const c = content as ImplementationHandoverContent
            return (
                <div className="flex flex-col gap-3 text-xs">
                    {!!c.replacement_pr_urls?.length && (
                        <div className="flex flex-col gap-3">
                            <Text size="xs" variant="muted" render={<span />}>
                                {c.replacement_pr_urls.length === 1 ? 'Replacement PR' : 'Replacement PRs'}
                            </Text>
                            {c.replacement_pr_urls.map((url) => renderPullRequest(url))}
                        </div>
                    )}
                    {!!Object.keys(c.results ?? {}).length && (
                        <div className="flex flex-col gap-3 border-t border-border pt-3">
                            <Text size="xs" variant="muted" render={<span />}>
                                {Object.keys(c.results ?? {}).length === 1 ? 'Previous PR' : 'Previous PRs'}
                            </Text>
                            {Object.entries(c.results ?? {}).map(([url, result]) => renderPullRequest(url, result))}
                        </div>
                    )}
                    {c.explanation ? (
                        <QuillLogDisclosure label="Replacement details" defaultOpen={c.status !== 'completed'}>
                            <QuillReasoningBody text={c.explanation} />
                        </QuillLogDisclosure>
                    ) : null}
                </div>
            )
        }
        case 'ranking_score': {
            const score = readRankingScore(content)
            return score ? <QuillRankingScoreBody score={score} /> : null
        }
        default: {
            const value = (content as { content?: unknown })?.content
            return typeof value === 'string' && value.trim() ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    {value}
                </Text>
            ) : null
        }
    }
}

function QuillTimelineMarker({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <span className="z-10 flex size-5 shrink-0 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
            {children}
        </span>
    )
}

function QuillArtefactRow({
    reportId,
    artefact,
    knownTasks,
    knownSignals,
    knownPullRequests,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
    knownSignals?: Map<string, SignalNode>
    knownPullRequests: Map<string, SignalReportPullRequestApi>
}): JSX.Element {
    const monitoringEnabled = useFeatureFlag('SIGNALS_REPORT_MONITORING')
    const notesEnabled = useFeatureFlag('SIGNALS_REPORT_NOTES')
    const signal = artefactFindingSignal(artefact, knownSignals)
    const location = artefactLocationLabel(artefact)
    const attribution = artefactAttributionLabel(artefact)
    const summary = renderQuillArtefactSummary(artefact, monitoringEnabled)
    const body = signal ? (
        <QuillSignalFindingBody signal={signal} />
    ) : (
        renderQuillArtefactBody({ reportId, artefact, knownTasks, knownPullRequests, monitoringEnabled, notesEnabled })
    )
    const MarkerIcon = artefactMarkerIcon(artefact)

    return (
        <div className="relative flex gap-3 pb-4 last:pb-0">
            <QuillTimelineMarker>
                <MarkerIcon className="size-3" />
            </QuillTimelineMarker>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <Text size="sm" weight="medium" render={<span />}>
                        {prActivityTitle(artefact)}
                    </Text>
                    {summary}
                    {location ? (
                        <span className="min-w-0 truncate font-mono text-xs text-subtle-foreground">{location}</span>
                    ) : null}
                    <span className="inline-flex items-center gap-1.5 text-xs text-subtle-foreground">
                        {attribution ? <span>{attribution}</span> : null}
                        {attribution ? <span aria-hidden>·</span> : null}
                        <TZLabel time={artefact.created_at} />
                    </span>
                </div>
                {body ? (
                    <div className="w-full min-w-0">
                        {artefactBodyHasOwnCard(artefact) ? (
                            body
                        ) : (
                            <QuillActivityBodyCard>{body}</QuillActivityBodyCard>
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

/** Stands in for the scout notes the work log stopped keeping, above the newest note that is left. */
function QuillCollapsedNotesRow({ count }: { count: number }): JSX.Element {
    return (
        <div className="relative flex gap-3 pb-4 last:pb-0">
            <QuillTimelineMarker>
                <IconComment className="size-3" />
            </QuillTimelineMarker>
            <Text size="xs" render={<span />} className="min-w-0 flex-1 text-subtle-foreground">
                Corroborated {count} more {count === 1 ? 'time' : 'times'} by a scout, with nothing new to add.
            </Text>
        </div>
    )
}

/** The quill sibling of `ArtefactLogList`: the report's work-log, newest first. Returns null when empty. */
export function QuillArtefactLogList({
    reportId,
    artefacts,
    knownTasks,
    knownSignals,
    pullRequests,
    collapsedNoteCount = 0,
}: {
    reportId: string
    artefacts: SignalReportArtefact[]
    /** Tasks the detail logic already resolved, keyed by id — `task_run` rows reuse these instead of refetching. */
    knownTasks?: Map<string, Task>
    knownSignals?: Map<string, SignalNode>
    pullRequests?: readonly SignalReportPullRequestApi[]
    /** Scout notes the report received beyond the entries kept below, shown as one line instead. */
    collapsedNoteCount?: number
}): JSX.Element | null {
    if (artefacts.length === 0) {
        return null
    }
    const { ordered, anchorIndex } = orderArtefactLog(artefacts, collapsedNoteCount)
    const knownPullRequests = new Map(pullRequests?.map((pr) => [pr.url, pr]))
    if (ordered.length === 0) {
        return null
    }
    return (
        <div className="relative">
            <span className="absolute start-2.5 top-2.5 bottom-2.5 w-px bg-border" aria-hidden />
            {ordered.map((artefact, index) => (
                // Fragment rather than a wrapper element: `last:pb-0` on the rows resolves against this
                // container's children, and a wrapper would make every row the last.
                <Fragment key={artefact.id}>
                    {index === anchorIndex ? <QuillCollapsedNotesRow count={collapsedNoteCount} /> : null}
                    <QuillArtefactRow
                        reportId={reportId}
                        artefact={artefact}
                        knownTasks={knownTasks}
                        knownSignals={knownSignals}
                        knownPullRequests={knownPullRequests}
                    />
                </Fragment>
            ))}
        </div>
    )
}
