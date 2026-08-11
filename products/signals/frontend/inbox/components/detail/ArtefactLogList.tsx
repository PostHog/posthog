import { type ComponentType, useState } from 'react'

import {
    IconActivity,
    IconArchive,
    IconCode,
    IconComment,
    IconCommit,
    IconFlag,
    IconGitRepository,
    IconListCheck,
    IconListTreeConnected,
    IconPeople,
    IconPencil,
    IconSearch,
    IconShield,
    IconTerminal,
    IconVideoCamera,
    IconExternal,
} from '@posthog/icons'
import { LemonCard, LemonTag, type LemonTagType, Link, ProfilePicture } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { Task } from 'products/posthog_ai/frontend/types/taskTypes'

import { PRIORITY_TAG_TYPE } from '../../filterOptions'
import { SignalCard } from '../../SignalCard'
import { EnrichedReviewer, SignalReportActionability, SignalReportPriority, SignalReportArtefact } from '../../types'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalCardDisclosureProvider } from '../signalCards/SignalCardShell'
import { ArtefactCommit } from './ArtefactCommit'
import { ArtefactTaskRun } from './ArtefactTaskRun'
import {
    artefactAttributionLabel,
    artefactLocationLabel,
    artefactTypeLabel,
    CodeReviewContent,
    CodeReferenceContent,
    CommitContent,
    DismissalContent,
    LineReferenceContent,
    NoteContent,
    RelatedToContent,
    RepoSelectionContent,
    SignalFindingContent,
    SummaryChangeContent,
    TaskRunArtefactContent,
    TitleChangeContent,
} from './artefactTypes'

/** Map a file extension to a CodeSnippet language for syntax highlighting; falls back to plain text. */
function languageFromPath(path: string | undefined): Language {
    const ext = path?.split('.').pop()?.toLowerCase()
    switch (ext) {
        case 'ts':
        case 'tsx':
            return Language.TypeScript
        case 'js':
        case 'jsx':
        case 'mjs':
        case 'cjs':
            return Language.JavaScript
        case 'py':
            return Language.Python
        case 'go':
            return Language.Go
        case 'rb':
            return Language.Ruby
        case 'java':
            return Language.Java
        case 'kt':
            return Language.Kotlin
        case 'php':
            return Language.PHP
        case 'cs':
            return Language.CSharp
        case 'swift':
            return Language.Swift
        case 'sql':
            return Language.SQL
        case 'json':
            return Language.JSON
        case 'yaml':
        case 'yml':
            return Language.YAML
        case 'sh':
        case 'bash':
            return Language.Bash
        case 'html':
        case 'xml':
            return Language.XML
        default:
            return Language.Text
    }
}

/** Replace dashes/underscores with spaces and capitalize — for enum-ish strings (dismissal reasons). */
function prettify(value: string): string {
    return capitalizeFirstLetter(value.replace(/[-_]/g, ' '))
}

/** Friendly labels for known dismissal reason codes; unknown values fall back to a humanized form. */
const DISMISS_REASON_LABELS: Record<string, string> = {
    slack_dismiss: 'Dismissed from Slack',
}

const ARTEFACT_MARKER: Record<string, ComponentType<{ className?: string }>> = {
    code_reference: IconCode,
    line_reference: IconCode,
    commit: IconCommit,
    task_run: IconTerminal,
    note: IconComment,
    priority_judgment: IconFlag,
    actionability_judgment: IconListCheck,
    safety_judgment: IconShield,
    signal_finding: IconSearch,
    suggested_reviewers: IconPeople,
    repo_selection: IconGitRepository,
    dismissal: IconArchive,
    video_segment: IconVideoCamera,
    title_change: IconPencil,
    summary_change: IconPencil,
    related_to: IconListTreeConnected,
    code_review: IconListCheck,
}

function dismissReasonLabel(reason: string): string {
    return DISMISS_REASON_LABELS[reason] ?? prettify(reason)
}

/** A short relevance / context note above a code block. */
function RelevanceNote({ note }: { note?: string }): JSX.Element | null {
    if (!note?.trim()) {
        return null
    }
    return <span className="block text-secondary text-xs">{note}</span>
}

/** A read-only highlighted code block sized for the activity log. */
function CodeRefBlock({ code, language }: { code: string; language: Language }): JSX.Element {
    return (
        <div className="mt-1.5">
            <CodeSnippet language={language} compact wrap>
                {code}
            </CodeSnippet>
        </div>
    )
}

function ActivityBodyCard({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="w-full p-2 shadow-none">
            {children}
        </LemonCard>
    )
}

function ReasoningBody({ text }: { text: string }): JSX.Element {
    return <p className="m-0 text-xs leading-relaxed text-secondary">{text}</p>
}

function NoteBody({ note, author }: { note: string; author?: string }): JSX.Element {
    return (
        <div className="w-full">
            <LemonMarkdown className="text-xs text-secondary leading-normal" disableImages>
                {note}
            </LemonMarkdown>
            {author?.trim() ? <span className="mt-1 block text-xs text-tertiary">By {author}</span> : null}
        </div>
    )
}

function ContentChangeBody({
    previous,
    current,
    markdown = false,
}: {
    previous?: string | null
    current: string
    markdown?: boolean
}): JSX.Element {
    const renderText = (text: string, muted: boolean): JSX.Element => {
        const color = muted ? 'text-secondary' : 'text-default'
        return markdown ? (
            <LemonMarkdown className={`text-xs leading-normal ${color}`} disableImages>
                {text}
            </LemonMarkdown>
        ) : (
            <span className={`text-xs ${color}`}>{text}</span>
        )
    }

    return (
        <div className="flex w-full min-w-0 flex-col gap-2">
            <div className="min-w-0">{renderText(current, false)}</div>
            {previous?.trim() ? (
                <div className="border-l pl-2">
                    <span className="mb-0.5 block text-xs font-medium text-tertiary">Previous</span>
                    {renderText(previous, true)}
                </div>
            ) : null}
        </div>
    )
}

function ReviewersBody({ reviewers }: { reviewers: EnrichedReviewer[] }): JSX.Element {
    if (reviewers.length === 0) {
        return <span className="text-tertiary text-xs">No reviewers assigned.</span>
    }
    return (
        <div className="flex flex-wrap gap-1.5">
            {reviewers.map((reviewer) => {
                const name = reviewer.user?.first_name || reviewer.github_name || reviewer.github_login
                return (
                    <Link
                        key={reviewer.github_login}
                        to={`https://github.com/${reviewer.github_login}`}
                        target="_blank"
                        disableClientSideRouting
                        className="inline-flex items-center gap-1.5 rounded px-1.5 py-1 text-xs no-underline hover:bg-fill-highlight-50"
                    >
                        <ProfilePicture user={reviewer.user} name={name} size="xs" />
                        <span className="text-default">{name}</span>
                        <span className="font-mono text-tertiary">@{reviewer.github_login}</span>
                        <IconExternal className="size-3 text-tertiary" />
                    </Link>
                )
            })}
        </div>
    )
}

function RepoSelectionBody({ content }: { content: RepoSelectionContent }): JSX.Element | null {
    if (!content.reason?.trim()) {
        return null
    }
    return <ReasoningBody text={content.reason} />
}

function SignalFindingBody({ signal }: { signal: SignalNode }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="w-full">
            <SignalCardDisclosureProvider expanded={expanded} onChange={setExpanded}>
                <SignalCard signal={signal} />
            </SignalCardDisclosureProvider>
        </div>
    )
}

function RelatedReportBody({ content }: { content: RelatedToContent }): JSX.Element | null {
    if (!content.report_id) {
        return null
    }
    return (
        <Link to={urls.inboxReport('reports', content.report_id)} className="inline-flex items-center gap-1 text-xs">
            Open report <IconExternal className="size-3" />
        </Link>
    )
}

const CODE_REVIEW_OUTCOME: Record<NonNullable<CodeReviewContent['outcome']>, { label: string; type: LemonTagType }> = {
    published: { label: 'Published on GitHub', type: 'success' },
    stored: { label: 'Review saved', type: 'muted' },
    failed: { label: 'Review failed', type: 'danger' },
}

function CodeReviewBody({ content }: { content: CodeReviewContent }): JSX.Element | null {
    const counts = content.counts
    const reviewUrl = content.review_url || content.pr_url
    const hasContent = content.repository || counts || reviewUrl

    if (!hasContent) {
        return null
    }

    return (
        <div className="flex w-full flex-col items-start gap-1.5">
            <div className="flex flex-wrap items-center gap-1">
                {(counts?.must_fix ?? 0) > 0 ? (
                    <LemonTag size="small" type="danger">
                        {counts?.must_fix} must fix
                    </LemonTag>
                ) : null}
                {(counts?.should_fix ?? 0) > 0 ? (
                    <LemonTag size="small" type="warning">
                        {counts?.should_fix} should fix
                    </LemonTag>
                ) : null}
                {(counts?.consider ?? 0) > 0 ? (
                    <LemonTag size="small" type="muted">
                        {counts?.consider} consider
                    </LemonTag>
                ) : null}
            </div>
            {content.repository ? (
                <span className="font-mono text-xs text-tertiary">
                    {content.repository}
                    {content.head_branch ? `@${content.head_branch}` : ''}
                    {content.head_sha ? ` · ${content.head_sha.slice(0, 12)}` : ''}
                </span>
            ) : null}
            {reviewUrl ? (
                <Link
                    to={reviewUrl}
                    target="_blank"
                    disableClientSideRouting
                    className="inline-flex items-center gap-1 text-xs"
                >
                    View review <IconExternal className="size-3" />
                </Link>
            ) : null}
        </div>
    )
}

function renderArtefactSummary(artefact: SignalReportArtefact): JSX.Element | null {
    const content = artefact.content

    switch (artefact.type) {
        case 'priority_judgment': {
            const priority = (content as { priority?: SignalReportPriority }).priority
            return priority ? (
                <LemonTag size="small" type={PRIORITY_TAG_TYPE[priority] ?? 'muted'}>
                    {priority}
                </LemonTag>
            ) : null
        }
        case 'actionability_judgment': {
            const c = content as {
                actionability?: SignalReportActionability
                already_addressed?: boolean
            }
            if (!c.actionability && !c.already_addressed) {
                return null
            }
            return (
                <span className="inline-flex items-center gap-1">
                    <SignalReportActionabilityBadge actionability={c.actionability} />
                    {c.already_addressed ? (
                        <LemonTag size="small" type="warning">
                            Already addressed
                        </LemonTag>
                    ) : null}
                </span>
            )
        }
        case 'safety_judgment': {
            const choice = (content as { choice?: boolean }).choice
            if (typeof choice !== 'boolean') {
                return null
            }
            return (
                <LemonTag size="small" type={choice ? 'success' : 'danger'}>
                    {choice ? 'Safe to act on' : 'Unsafe'}
                </LemonTag>
            )
        }
        case 'repo_selection': {
            const repository = (content as RepoSelectionContent).repository
            return repository ? <span className="font-mono text-xs text-secondary">{repository}</span> : null
        }
        case 'dismissal': {
            const reason = (content as DismissalContent).reason
            return reason ? (
                <LemonTag size="small" type="muted">
                    {dismissReasonLabel(reason)}
                </LemonTag>
            ) : null
        }
        case 'code_review': {
            const outcome = (content as CodeReviewContent).outcome
            const meta = outcome ? CODE_REVIEW_OUTCOME[outcome] : null
            return meta ? (
                <LemonTag size="small" type={meta.type}>
                    {meta.label}
                </LemonTag>
            ) : null
        }
        default:
            return null
    }
}

function renderArtefactBody({
    reportId,
    artefact,
    knownTasks,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
}): JSX.Element | null {
    const content = artefact.content

    switch (artefact.type) {
        case 'code_reference': {
            const c = content as CodeReferenceContent
            return (
                <div>
                    <RelevanceNote note={c.relevance_note} />
                    {c.contents ? <CodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} /> : null}
                </div>
            )
        }
        case 'line_reference': {
            const c = content as LineReferenceContent
            return (
                <div>
                    <RelevanceNote note={c.note} />
                    {c.contents ? <CodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} /> : null}
                </div>
            )
        }
        case 'commit':
            return <ArtefactCommit reportId={reportId} artefactId={artefact.id} content={content as CommitContent} />
        case 'task_run': {
            const c = content as TaskRunArtefactContent
            return <ArtefactTaskRun content={c} knownTask={knownTasks?.get(c.task_id) ?? null} />
        }
        case 'note': {
            const c = content as NoteContent
            return <NoteBody note={c.note} author={c.author} />
        }
        case 'priority_judgment': {
            const c = content as { explanation?: string }
            return c.explanation ? <ReasoningBody text={c.explanation} /> : null
        }
        case 'actionability_judgment': {
            const c = content as { explanation?: string }
            return c.explanation ? <ReasoningBody text={c.explanation} /> : null
        }
        case 'safety_judgment': {
            const c = content as { explanation?: string }
            return c.explanation ? <ReasoningBody text={c.explanation} /> : null
        }
        case 'signal_finding':
            return null
        case 'suggested_reviewers':
            return <ReviewersBody reviewers={(content as unknown as EnrichedReviewer[]) ?? []} />
        case 'repo_selection':
            return <RepoSelectionBody content={content as RepoSelectionContent} />
        case 'related_to':
            return <RelatedReportBody content={content as RelatedToContent} />
        case 'code_review':
            return <CodeReviewBody content={content as CodeReviewContent} />
        case 'title_change': {
            const c = content as TitleChangeContent
            return <ContentChangeBody previous={c.old_title} current={c.new_title ?? ''} />
        }
        case 'summary_change': {
            const c = content as SummaryChangeContent
            return <ContentChangeBody previous={c.old_summary} current={c.new_summary ?? ''} markdown />
        }
        case 'dismissal': {
            const c = content as DismissalContent
            return c.note ? <RelevanceNote note={c.note} /> : null
        }
        default: {
            const value = (content as { content?: unknown })?.content
            return typeof value === 'string' && value.trim() ? (
                <span className="text-tertiary text-xs">{value}</span>
            ) : null
        }
    }
}

function ArtefactRow({
    reportId,
    artefact,
    knownTasks,
    knownSignals,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
    knownSignals?: Map<string, SignalNode>
}): JSX.Element {
    const signalId = artefact.type === 'signal_finding' ? (artefact.content as SignalFindingContent).signal_id : null
    const signal = signalId ? knownSignals?.get(signalId) : undefined
    const location = artefactLocationLabel(artefact)
    const attribution = artefactAttributionLabel(artefact)
    const summary = renderArtefactSummary(artefact)
    const body = signal ? <SignalFindingBody signal={signal} /> : renderArtefactBody({ reportId, artefact, knownTasks })
    const bodyHasOwnCard = artefact.type === 'signal_finding' || artefact.type === 'commit'
    const MarkerIcon = ARTEFACT_MARKER[artefact.type] ?? IconActivity

    return (
        <div className="relative flex gap-3 pb-4 last:pb-0">
            <span className="z-10 flex size-5 shrink-0 items-center justify-center rounded-full border bg-surface-primary text-secondary">
                <MarkerIcon className="size-3" />
            </span>
            <div className="min-w-0 flex-1">
                <div
                    className={
                        body
                            ? 'mb-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5'
                            : 'flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5'
                    }
                >
                    <span className="font-medium text-sm text-default">{artefactTypeLabel(artefact.type)}</span>
                    {summary}
                    {location ? <span className="truncate font-mono text-xs text-tertiary">{location}</span> : null}
                    <span className="inline-flex items-center gap-1.5 text-xs text-tertiary">
                        {attribution ? <span>{attribution}</span> : null}
                        {attribution ? <span aria-hidden>·</span> : null}
                        <TZLabel time={artefact.created_at} />
                    </span>
                </div>
                {body ? (
                    <div className="min-w-0 w-full">
                        {bodyHasOwnCard ? body : <ActivityBodyCard>{body}</ActivityBodyCard>}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

/**
 * The report's work-log: every artefact rendered chronologically with a tailored body — judgments,
 * findings, code references, diffs, commits, task runs, notes, and reviewers. Mirrors desktop
 * `ArtefactLogList`. Returns null when there are no artefacts.
 */
export function ArtefactLogList({
    reportId,
    artefacts,
    knownTasks,
    knownSignals,
}: {
    reportId: string
    artefacts: SignalReportArtefact[]
    /** Tasks the detail logic already resolved, keyed by id — `task_run` rows reuse these instead of refetching. */
    knownTasks?: Map<string, Task>
    knownSignals?: Map<string, SignalNode>
}): JSX.Element | null {
    if (artefacts.length === 0) {
        return null
    }
    const ordered = [...artefacts].sort((a, b) => b.created_at.localeCompare(a.created_at))
    return (
        <div className="relative">
            <span className="absolute bottom-2.5 left-2.5 top-2.5 w-px bg-border" aria-hidden />
            {ordered.map((artefact) => (
                <ArtefactRow
                    key={artefact.id}
                    reportId={reportId}
                    artefact={artefact}
                    knownTasks={knownTasks}
                    knownSignals={knownSignals}
                />
            ))}
        </div>
    )
}
