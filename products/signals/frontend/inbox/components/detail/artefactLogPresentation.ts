import type { ComponentType } from 'react'

import {
    IconActivity,
    IconCalendar,
    IconCheckCircle,
    IconCode,
    IconComment,
    IconCommit,
    IconFlag,
    IconGitRepository,
    IconHide,
    IconListCheck,
    IconListTreeConnected,
    IconPause,
    IconPencil,
    IconPeople,
    IconPullRequest,
    IconRefresh,
    IconSearch,
    IconShield,
    IconTerminal,
    IconTrending,
    IconVideoCamera,
} from '@posthog/icons'
import type { LemonTagType } from '@posthog/lemon-ui'

import { Language } from 'lib/components/CodeSnippet'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import type { SignalNode } from 'scenes/debug/signals/types'

import { Task } from 'products/posthog_ai/frontend/types/taskTypes'
import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import { INBOX_RANKING_SCORES, PRIORITY_TAG_TYPE, rankingScoreForHead } from '../../filterOptions'
import { EnrichedReviewer, SignalReportActionability, SignalReportArtefact, SignalReportPriority } from '../../types'
import { dismissalReasonLabel } from '../../utils/dismissalReasons'
import { parsePrUrlParts, type ParsedPrUrlParts } from '../../utils/reportPresentation'
import {
    CheckLifecycleContent,
    CheckResultContent,
    CodeReviewContent,
    DismissalContent,
    ImplementationDecisionContent,
    RankingHead,
    RepoSelectionContent,
    selectVisibleReportActivity,
    SignalFindingContent,
    WORK_RELEASE_REASON_LABELS,
    WorkClaimContent,
    WorkReleaseContent,
} from './artefactTypes'
import { CHECK_LIFECYCLE_ENTRIES } from './reportCheckPresentation'

/**
 * View-independent pieces of the activity log, shared by `ArtefactLogList` and its quill sibling so
 * the two only differ in markup.
 */

/** Map a file extension to a CodeSnippet language for syntax highlighting; falls back to plain text. */
export function languageFromPath(path: string | undefined): Language {
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
export function prettify(value: string): string {
    return capitalizeFirstLetter(value.replace(/[-_]/g, ' '))
}

/** Friendly labels for known dismissal reason codes; unknown values fall back to a humanized form. */
const DISMISS_REASON_LABELS: Record<string, string> = {
    slack_dismiss: 'Dismissed from Slack',
}

function dismissReasonLabel(reason: string): string {
    return DISMISS_REASON_LABELS[reason] ?? dismissalReasonLabel(reason) ?? prettify(reason)
}

const ARTEFACT_MARKER: Record<string, ComponentType<{ className?: string }>> = {
    pull_request: IconPullRequest,
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
    dismissal: IconHide,
    video_segment: IconVideoCamera,
    scout_note_left: IconPencil,
    title_change: IconPencil,
    summary_change: IconPencil,
    related_to: IconListTreeConnected,
    report_link: IconListTreeConnected,
    autostart_skip: IconPause,
    code_review: IconListCheck,
    check_result: IconCalendar,
    check_observation: IconCalendar,
    check_scheduled: IconCalendar,
    check_expired: IconCalendar,
    check_cancelled: IconCalendar,
    implementation_decision: IconRefresh,
    implementation_replacement: IconRefresh,
    implementation_handover: IconRefresh,
    ranking_score: IconTrending,
    work_claim: IconPeople,
    work_release: IconPeople,
}

/** The icon on an entry's timeline marker. */
export function artefactMarkerIcon(artefact: SignalReportArtefact): ComponentType<{ className?: string }> {
    return artefact.type === 'dismissal' && (artefact.content as DismissalContent).state === 'resolved'
        ? IconCheckCircle
        : (ARTEFACT_MARKER[artefact.type] ?? IconActivity)
}

/** Commit and signal-finding bodies draw their own card, so the row must not wrap them in another. */
export function artefactBodyHasOwnCard(artefact: SignalReportArtefact): boolean {
    return artefact.type === 'signal_finding' || artefact.type === 'commit'
}

/** The resolved signal behind a `signal_finding` entry, when the detail logic already loaded it. */
export function artefactFindingSignal(
    artefact: SignalReportArtefact,
    knownSignals?: Map<string, SignalNode>
): SignalNode | undefined {
    const signalId = artefact.type === 'signal_finding' ? (artefact.content as SignalFindingContent).signal_id : null
    return signalId ? knownSignals?.get(signalId) : undefined
}

const CODE_REVIEW_OUTCOME: Record<NonNullable<CodeReviewContent['outcome']>, { label: string; type: LemonTagType }> = {
    published: { label: 'Published on GitHub', type: 'success' },
    stored: { label: 'Review saved', type: 'muted' },
    failed: { label: 'Review failed', type: 'danger' },
}

const CHECK_OUTCOME: Record<NonNullable<CheckResultContent['outcome']>, { label: string; type: LemonTagType }> = {
    passed: { label: 'Still holds', type: 'success' },
    failed: { label: 'No longer holds', type: 'danger' },
    errored: { label: "Couldn't measure", type: 'warning' },
    inconclusive: { label: 'Inconclusive', type: 'info' },
}

/** What sits beside an entry's title: a tag, a line of text, or the actionability badge. */
export type ArtefactSummary =
    | { kind: 'tag'; label: string; type: LemonTagType }
    | { kind: 'text'; text: string; mono?: boolean }
    | { kind: 'actionability'; actionability?: SignalReportActionability; alreadyAddressed: boolean }

export function artefactSummary(artefact: SignalReportArtefact, monitoringEnabled: boolean): ArtefactSummary | null {
    const content = artefact.content

    switch (artefact.type) {
        case 'priority_judgment': {
            const priority = (content as { priority?: SignalReportPriority }).priority
            return priority ? { kind: 'tag', label: priority, type: PRIORITY_TAG_TYPE[priority] ?? 'muted' } : null
        }
        case 'actionability_judgment': {
            const c = content as {
                actionability?: SignalReportActionability
                already_addressed?: boolean
            }
            if (!c.actionability && !c.already_addressed) {
                return null
            }
            return { kind: 'actionability', actionability: c.actionability, alreadyAddressed: !!c.already_addressed }
        }
        case 'safety_judgment': {
            const choice = (content as { choice?: boolean }).choice
            if (typeof choice !== 'boolean') {
                return null
            }
            return { kind: 'tag', label: choice ? 'Safe to act on' : 'Unsafe', type: choice ? 'success' : 'danger' }
        }
        case 'repo_selection': {
            const repository = (content as RepoSelectionContent).repository
            return repository ? { kind: 'text', text: repository, mono: true } : null
        }
        case 'dismissal': {
            const reason = (content as DismissalContent).reason
            return reason ? { kind: 'tag', label: dismissReasonLabel(reason), type: 'muted' } : null
        }
        case 'code_review': {
            const outcome = (content as CodeReviewContent).outcome
            const meta = outcome ? CODE_REVIEW_OUTCOME[outcome] : null
            return meta ? { kind: 'tag', ...meta } : null
        }
        case 'check_observation':
            return { kind: 'tag', label: 'Interim measurement', type: 'muted' }
        case 'check_result': {
            const outcome = (content as CheckResultContent).outcome
            const meta = outcome ? CHECK_OUTCOME[outcome] : null
            return meta ? { kind: 'tag', ...meta } : null
        }
        case 'check_scheduled':
        case 'check_expired':
        case 'check_cancelled': {
            const { tag } = CHECK_LIFECYCLE_ENTRIES[artefact.type](content as CheckLifecycleContent, monitoringEnabled)
            return { kind: 'tag', ...tag }
        }
        case 'implementation_decision': {
            const { supersede, blocked_reason } = content as ImplementationDecisionContent
            if (typeof supersede !== 'boolean') {
                return null
            }
            return {
                kind: 'tag',
                label:
                    blocked_reason === 'revision_limit'
                        ? 'Replacement limit reached'
                        : supersede
                          ? 'Replacement recommended'
                          : 'Still the right fix',
                type: supersede ? 'warning' : 'muted',
            }
        }
        case 'work_claim': {
            const name = (content as WorkClaimContent).display_name
            return name?.trim() ? { kind: 'text', text: name } : null
        }
        case 'work_release': {
            const reason = (content as WorkReleaseContent).reason
            return reason && WORK_RELEASE_REASON_LABELS[reason]
                ? { kind: 'tag', label: WORK_RELEASE_REASON_LABELS[reason], type: 'muted' }
                : null
        }
        default:
            return null
    }
}

export function reviewerDisplayName(reviewer: EnrichedReviewer): string {
    return (
        reviewer.user?.first_name || reviewer.github_name || reviewer.github_login || reviewer.user?.email || 'Reviewer'
    )
}

/** Where a code review entry links to, and the repository line under its counts. */
export function codeReviewLinks(content: CodeReviewContent): {
    reviewUrl: string | undefined
    repository: string | null
} {
    return {
        reviewUrl: content.review_url || content.pr_url || undefined,
        repository: content.repository
            ? `${content.repository}${content.head_branch ? `@${content.head_branch}` : ''}${
                  content.head_sha ? ` · ${content.head_sha.slice(0, 12)}` : ''
              }`
            : null,
    }
}

/** The three scores first, in display order. Every other head stays behind a collapsed disclosure for debugging. */
export function splitRankingHeads(heads: RankingHead[]): { scoreHeads: RankingHead[]; otherHeads: RankingHead[] } {
    return {
        scoreHeads: INBOX_RANKING_SCORES.flatMap((score) => heads.filter((head) => head.name === score.head)),
        otherHeads: heads.filter((head) => !rankingScoreForHead(head.name)),
    }
}

/** What a pull request body needs from the report: the implementation task's title and the PR state. */
export function artefactPullRequestContext(
    url: string,
    knownPullRequests: Map<string, SignalReportPullRequestApi>,
    knownTasks?: Map<string, Task>
): { implementationTitle: string | undefined; state: SignalReportPullRequestApi['state'] | undefined } {
    const pr = knownPullRequests.get(url)
    const taskId = pr?.attached_by?.task_id
    return {
        implementationTitle: taskId ? knownTasks?.get(taskId)?.title : undefined,
        state: pr?.merged ? 'merged' : pr?.state,
    }
}

export type ArtefactPullRequestOutcome = 'closed' | 'already_closed' | 'skipped'

export interface ArtefactPullRequestView {
    pr: ParsedPrUrlParts | null
    repoLabel: string
    statusLabel: string
    statusTagType: LemonTagType
    linkText: string
    outcomeLabel: string | null
}

export function artefactPullRequestView({
    url,
    implementationTitle,
    state,
    outcome,
}: {
    url: string
    implementationTitle?: string
    state?: SignalReportPullRequestApi['state']
    outcome?: ArtefactPullRequestOutcome
}): ArtefactPullRequestView {
    const pr = parsePrUrlParts(url)
    const title = implementationTitle?.replace(/^Implementation:\s*/i, '').trim()
    const status = state ?? 'unknown'
    return {
        pr,
        repoLabel: pr ? `${pr.repoSlug} · #${pr.number}` : 'Pull request',
        statusLabel: {
            unknown: 'Status unavailable',
            draft: 'Draft',
            open: 'Open',
            closed: 'Closed',
            merged: 'Merged',
        }[status],
        statusTagType: status === 'open' ? 'success' : status === 'merged' ? 'primary' : 'muted',
        linkText: title || (pr ? `Pull request #${pr.number}` : url),
        outcomeLabel: outcome
            ? outcome === 'skipped'
                ? 'Not closed by PostHog'
                : outcome === 'already_closed'
                  ? 'Already closed at replacement'
                  : 'Closed by PostHog'
            : null,
    }
}

/**
 * The log's entries newest-first, and where the collapsed scout notes line goes. The dropped notes
 * came after every note still in the log, so they sit above the newest surviving note. With no note
 * left to anchor to they lead the log. `anchorIndex` is -1 when there is nothing collapsed.
 */
export function orderArtefactLog(
    artefacts: SignalReportArtefact[],
    collapsedNoteCount: number
): { ordered: SignalReportArtefact[]; anchorIndex: number } {
    const ordered = selectVisibleReportActivity(artefacts).sort((a, b) => b.created_at.localeCompare(a.created_at))
    const anchorIndex =
        collapsedNoteCount > 0
            ? Math.max(
                  0,
                  ordered.findIndex((a) => a.type === 'note')
              )
            : -1
    return { ordered, anchorIndex }
}
