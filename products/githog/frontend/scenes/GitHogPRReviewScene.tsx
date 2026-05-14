import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCode, IconGitBranch, IconPeople, IconPlus, IconRefresh, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { gitHogPRDiffLogic } from './gitHogPRDiffLogic'
import {
    DashboardReference,
    EventReach,
    FlagReach,
    FlagReference,
    GitHogPRImpactLogicProps,
    IssueReference,
    LLMPick,
    RelatedSignal,
    gitHogPRImpactLogic,
} from './gitHogPRImpactLogic'

export const scene: SceneExport<GitHogPRImpactLogicProps> = {
    component: GitHogPRReviewScene,
    logic: gitHogPRImpactLogic,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: number ?? '',
    }),
}

// ─── Sample data ────────────────────────────────────────────────────────────

const SAMPLE_PR = {
    number: 1234,
    title: 'feat(insights): add retention graph export with multi-format support',
    author: 'Sarah Chen',
    sourceBranch: 'feat/retention-export',
    targetBranch: 'main',
    createdAt: '3 days ago',
    stats: { additions: 342, deletions: 89, changedFiles: 12, commits: 7 },
    reviewers: [
        { name: 'Marcus Webb', initials: 'MW', status: 'changes_requested' as const },
        { name: 'Priya Kapoor', initials: 'PK', status: 'approved' as const },
        { name: 'James Liu', initials: 'JL', status: 'pending' as const },
    ],
    labels: ['enhancement', 'insights'],
    comments: [
        {
            id: 1,
            author: 'Marcus Webb',
            initials: 'MW',
            timestamp: '2 days ago',
            body: "Should we guard against exporting when the graph hasn't finished loading? Right now it could fail silently.",
            reviewType: 'changes_requested' as const,
        },
        {
            id: 2,
            author: 'Sarah Chen',
            initials: 'SC',
            timestamp: '2 days ago',
            body: 'Good catch — added a loading guard and a toast for the not-ready state. Updated in the latest commit.',
            reviewType: 'reply' as const,
        },
        {
            id: 3,
            author: 'Priya Kapoor',
            initials: 'PK',
            timestamp: '1 day ago',
            body: 'LGTM. The CSV implementation is clean.',
            reviewType: 'approved' as const,
        },
        {
            id: 4,
            author: 'James Liu',
            initials: 'JL',
            timestamp: '4 hours ago',
            body: 'Reviewing now, will have feedback shortly.',
            reviewType: 'comment' as const,
        },
    ],
    changedFiles: [
        { name: 'RetentionGraph.tsx', additions: 89, deletions: 12 },
        { name: 'exportUtils.ts', additions: 134, deletions: 3, isNew: true },
        { name: 'InsightActionBar.tsx', additions: 45, deletions: 28 },
        { name: 'retentionExporter.ts', additions: 67, deletions: 0, isNew: true },
        { name: 'types.ts', additions: 7, deletions: 2 },
    ],
}

// ─── Widget registry ─────────────────────────────────────────────────────────

type WidgetType = 'conversation' | 'stats' | 'files' | 'reviewers' | 'impact' | 'diff'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; column: 'main' | 'side' }> = {
    conversation: { label: 'Conversation', description: 'Comments and review discussion', column: 'main' },
    diff: { label: 'Diff', description: 'Unified diff fetched from GitHub', column: 'main' },
    files: { label: 'Files changed', description: 'Modified files with line counts', column: 'main' },
    impact: {
        label: 'Blast radius',
        description: 'Users, sessions, and surfaces this PR touches in production',
        column: 'main',
    },
    stats: { label: 'Stats', description: 'Additions, deletions, and commits', column: 'side' },
    reviewers: { label: 'Reviewers', description: 'Review status per reviewer', column: 'side' },
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Avatar({ initials, size = 'md' }: { initials: string; size?: 'sm' | 'md' }): JSX.Element {
    const cls = size === 'sm' ? 'size-7 text-xs' : 'size-8 text-sm'
    return (
        <div
            className={`${cls} rounded-full bg-fill-highlight-100 flex items-center justify-center font-semibold text-secondary shrink-0`}
        >
            {initials}
        </div>
    )
}

function ReviewerDot({ status }: { status: 'approved' | 'changes_requested' | 'pending' }): JSX.Element {
    if (status === 'approved') {
        return <IconCheck className="size-4 text-success" />
    }
    if (status === 'changes_requested') {
        return <IconX className="size-4 text-danger" />
    }
    return <span className="size-2 rounded-full bg-border-bold inline-block mt-1" />
}

function WidgetShell({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} closeable onClose={onRemove} className="p-0 overflow-hidden">
            {children}
        </LemonCard>
    )
}

// ─── Individual widgets ───────────────────────────────────────────────────────

function ConversationWidget(): JSX.Element {
    const { comments } = SAMPLE_PR
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Conversation</span>
                <span className="text-xs text-secondary">{comments.length} comments</span>
            </div>
            {comments.map((c) => (
                <div key={c.id} className="px-4 py-4 flex gap-x-3">
                    <Avatar initials={c.initials} />
                    <div className="flex flex-col gap-y-1.5 flex-1 min-w-0">
                        <div className="flex items-center gap-x-2 flex-wrap">
                            <span className="font-semibold text-sm">{c.author}</span>
                            <span className="text-xs text-secondary">{c.timestamp}</span>
                            {c.reviewType === 'approved' && (
                                <LemonTag type="success" size="small" icon={<IconCheck />}>
                                    Approved
                                </LemonTag>
                            )}
                            {c.reviewType === 'changes_requested' && (
                                <LemonTag type="danger" size="small" icon={<IconX />}>
                                    Changes requested
                                </LemonTag>
                            )}
                        </div>
                        <p className="text-sm text-primary my-0 leading-relaxed">{c.body}</p>
                    </div>
                </div>
            ))}
        </div>
    )
}

function StatsWidget(): JSX.Element {
    const { stats } = SAMPLE_PR
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3">
                <span className="font-semibold text-sm">Stats</span>
            </div>
            <div className="grid grid-cols-2 divide-x divide-y divide-border">
                {[
                    { label: 'Additions', value: `+${stats.additions}`, className: 'text-success' },
                    { label: 'Deletions', value: `-${stats.deletions}`, className: 'text-danger' },
                    { label: 'Files', value: stats.changedFiles, className: '' },
                    { label: 'Commits', value: stats.commits, className: '' },
                ].map(({ label, value, className }) => (
                    <div key={label} className="flex flex-col gap-y-0.5 px-4 py-4">
                        <span className={`text-2xl font-bold tabular-nums ${className}`}>{value}</span>
                        <span className="text-xs text-secondary">{label}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function ReviewersWidget(): JSX.Element {
    const { reviewers } = SAMPLE_PR
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3">
                <span className="font-semibold text-sm">Reviewers</span>
            </div>
            <div className="px-4 py-3 flex flex-col gap-y-3">
                {reviewers.map((r) => (
                    <div key={r.initials} className="flex items-center gap-x-2.5">
                        <Avatar initials={r.initials} size="sm" />
                        <span className="text-sm flex-1">{r.name}</span>
                        <ReviewerDot status={r.status} />
                    </div>
                ))}
            </div>
        </div>
    )
}

function FilesWidget(): JSX.Element {
    const { changedFiles } = SAMPLE_PR
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Files changed</span>
                <span className="text-xs text-secondary">{changedFiles.length} files</span>
            </div>
            {changedFiles.map((f) => (
                <div key={f.name} className="px-4 py-2.5 flex items-center gap-x-3">
                    <IconCode className="size-3.5 text-muted shrink-0" />
                    <span className="text-sm flex-1 font-mono">{f.name}</span>
                    {f.isNew && (
                        <LemonTag type="success" size="small">
                            New
                        </LemonTag>
                    )}
                    <span className="text-xs text-success shrink-0">+{f.additions}</span>
                    <span className="text-xs text-danger shrink-0">-{f.deletions}</span>
                </div>
            ))}
        </div>
    )
}

function ImpactWidget({ owner, name, number }: GitHogPRImpactLogicProps): JSX.Element {
    const logic = gitHogPRImpactLogic({ owner, name, number })
    const { lookbackDays, report, reportLoading, reportError } = useValues(logic)
    const { setLookbackDays, computeImpact } = useActions(logic)

    const hasFlags = (report?.flag_references?.length ?? 0) > 0
    const hasEvents = (report?.event_references?.length ?? 0) > 0
    const hasDashboards = (report?.dashboard_references?.length ?? 0) > 0
    const hasIssues = (report?.issue_references?.length ?? 0) > 0
    const hasRelated = (report?.related_signals?.length ?? 0) > 0
    const hasLLM = !!report?.llm_analysis
    const hasAnySignal = hasFlags || hasEvents || hasDashboards || hasIssues || hasRelated || hasLLM
    const isInitialLoading = reportLoading && !report
    const isReloading = reportLoading && !!report
    const isErrored = !reportLoading && !!reportError && !report
    const isIdle = !reportLoading && !report && !reportError
    const hasResult = !reportLoading && !!report

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-x-3 flex-wrap">
                <span className="font-semibold text-sm flex items-center gap-x-2">
                    <IconPeople className="size-4 text-secondary" />
                    Blast radius
                </span>
                <div className="flex items-center gap-x-2">
                    <LemonSelect
                        size="small"
                        value={lookbackDays}
                        onChange={(v) => v && setLookbackDays(v)}
                        options={[
                            { value: 7, label: 'Last 7 days' },
                            { value: 30, label: 'Last 30 days' },
                            { value: 90, label: 'Last 90 days' },
                        ]}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={() => computeImpact({ refresh: true })}
                        loading={reportLoading}
                        tooltip="Bypass cache and recompute from scratch"
                    />
                </div>
            </div>

            <div className="px-4 py-2 text-xs text-secondary">
                Real users, sessions, and surfaces this PR touches — measured from PostHog activity, not configured
                rollouts.
            </div>

            {isInitialLoading && (
                <div className="px-4 py-6 flex flex-col items-center justify-center gap-y-1 text-secondary text-sm">
                    <div className="flex items-center gap-x-2">
                        <Spinner />
                        Measuring blast radius and asking the model…
                    </div>
                    <span className="text-xs text-muted">This can take up to ~30 seconds for large PRs.</span>
                </div>
            )}

            {isIdle && (
                <div className="px-4 py-6 text-sm text-secondary text-center">
                    Click <IconRefresh className="size-3.5 inline -mt-0.5" /> to measure blast radius for this PR.
                </div>
            )}

            {isErrored && (
                <div className="px-4 py-6 flex flex-col items-center gap-y-2 text-sm text-danger text-center">
                    <span>Failed to measure blast radius.</span>
                    <span className="text-xs text-secondary font-mono break-all max-w-prose">{reportError}</span>
                </div>
            )}

            {hasResult && !hasAnySignal && (
                <div className="px-4 py-6 flex flex-col gap-y-2 text-sm">
                    <span className="text-secondary text-center">
                        No PostHog flag or event references found in this PR
                        {isReloading ? ' (reloading…)' : '.'}
                    </span>
                    <span className="text-xs text-muted text-center">
                        Scanned {report.known_flag_count.toLocaleString()} flag keys and{' '}
                        {report.known_event_count.toLocaleString()} recent event names against{' '}
                        {report.changed_files.length} touched file
                        {report.changed_files.length === 1 ? '' : 's'}.
                    </span>
                </div>
            )}

            {hasResult && hasAnySignal && (
                <>
                    {hasLLM && report.llm_analysis && (
                        <div className="flex flex-col bg-fill-highlight-50">
                            {report.llm_analysis.affected && (
                                <div className="px-4 py-5 flex flex-col gap-y-2 border-b border-border">
                                    <div className="flex items-baseline gap-x-3 flex-wrap">
                                        <span className="text-3xl font-bold leading-none tabular-nums">
                                            {report.llm_analysis.affected.headline}
                                        </span>
                                        {(() => {
                                            const a = report.llm_analysis.affected
                                            const range =
                                                a.lower != null && a.upper != null && a.lower !== a.upper
                                                    ? `${a.lower.toLocaleString()}–${a.upper.toLocaleString()}`
                                                    : a.lower != null
                                                      ? a.lower.toLocaleString()
                                                      : a.upper != null
                                                        ? a.upper.toLocaleString()
                                                        : null
                                            const share =
                                                a.share_lower != null && a.share_upper != null
                                                    ? a.share_lower === a.share_upper
                                                        ? `${Math.round(a.share_upper * 100)}% of active`
                                                        : `${Math.round(a.share_lower * 100)}–${Math.round(a.share_upper * 100)}% of active`
                                                    : null
                                            const parts: string[] = []
                                            if (range) {
                                                parts.push(`${range} ${a.unit}`)
                                            }
                                            if (share) {
                                                parts.push(share)
                                            }
                                            if (parts.length === 0) {
                                                return null
                                            }
                                            return <span className="text-sm text-secondary">{parts.join(' · ')}</span>
                                        })()}
                                        <LemonTag
                                            type={
                                                report.llm_analysis.affected.confidence === 'high'
                                                    ? 'success'
                                                    : report.llm_analysis.affected.confidence === 'medium'
                                                      ? 'warning'
                                                      : 'muted'
                                            }
                                            size="small"
                                        >
                                            {report.llm_analysis.affected.confidence} confidence
                                        </LemonTag>
                                    </div>
                                    {report.llm_analysis.audience.length > 0 && (
                                        <div className="flex items-center gap-x-1.5 flex-wrap">
                                            {report.llm_analysis.audience.map((who: string, idx: number) => (
                                                <LemonTag key={idx} type="option" size="small">
                                                    {who}
                                                </LemonTag>
                                            ))}
                                        </div>
                                    )}
                                    {report.llm_analysis.affected.rationale && (
                                        <span className="text-xs text-muted leading-relaxed">
                                            {report.llm_analysis.affected.rationale}
                                        </span>
                                    )}
                                </div>
                            )}
                            <div className="px-4 py-4 flex flex-col gap-y-3">
                                <div className="flex items-start gap-x-2">
                                    <span className="text-xs font-semibold uppercase tracking-wide text-secondary mt-1 shrink-0">
                                        AI
                                    </span>
                                    <p className="text-sm font-medium leading-snug my-0 flex-1">
                                        {report.llm_analysis.headline}
                                    </p>
                                </div>
                                {report.llm_analysis.summary && (
                                    <p className="text-sm text-secondary leading-relaxed my-0 pl-7">
                                        {report.llm_analysis.summary}
                                    </p>
                                )}
                                {report.llm_analysis.top_picks.length > 0 && (
                                    <div className="pl-7 flex flex-col gap-y-1.5">
                                        {report.llm_analysis.top_picks.map((pick: LLMPick, idx: number) => (
                                            <div
                                                key={`${pick.kind}-${pick.key}-${idx}`}
                                                className="flex items-start gap-x-2"
                                            >
                                                <LemonTag type="muted" size="small">
                                                    {pick.kind}
                                                </LemonTag>
                                                <span className="text-sm font-mono shrink-0 truncate max-w-[40%]">
                                                    {pick.key}
                                                </span>
                                                <span className="text-xs text-secondary flex-1 leading-snug">
                                                    {pick.reason}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {report.llm_analysis.caveats.length > 0 && (
                                    <div className="pl-7 flex flex-col gap-y-0.5">
                                        {report.llm_analysis.caveats.map((c: string, idx: number) => (
                                            <span key={idx} className="text-xs text-muted">
                                                · {c}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {hasFlags && (
                        <div className="grid grid-cols-2 divide-x divide-y divide-border">
                            <div className="flex flex-col gap-y-0.5 px-4 py-4">
                                <span className="text-2xl font-bold tabular-nums">
                                    {report.intersection_users.toLocaleString()}
                                </span>
                                <span className="text-xs text-secondary">Users in blast radius</span>
                            </div>
                            <div className="flex flex-col gap-y-0.5 px-4 py-4">
                                <span className="text-2xl font-bold tabular-nums">
                                    {report.intersection_sessions.toLocaleString()}
                                </span>
                                <span className="text-xs text-secondary">Sessions hitting this code path</span>
                            </div>
                        </div>
                    )}

                    {hasDashboards && (
                        <>
                            <div className="px-4 py-3">
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    Surfaces this PR affects
                                </span>
                            </div>
                            {report.dashboard_references.map((ref: DashboardReference) => (
                                <div key={`${ref.kind}-${ref.id}`} className="px-4 py-3 flex items-center gap-x-3">
                                    <LemonTag type={ref.kind === 'dashboard' ? 'primary' : 'muted'} size="small">
                                        {ref.kind === 'dashboard' ? 'Dashboard' : 'Insight'}
                                    </LemonTag>
                                    <span className="text-sm flex-1 truncate">{ref.name}</span>
                                    <span
                                        className="text-xs text-muted truncate max-w-[40%]"
                                        title={ref.matched_keys.join(', ')}
                                    >
                                        via {ref.matched_keys.slice(0, 2).join(', ')}
                                        {ref.matched_keys.length > 2 ? ` +${ref.matched_keys.length - 2}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {hasIssues && (
                        <>
                            <div className="px-4 py-3">
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    Errors in this code area · last {report.lookback_days} days
                                </span>
                            </div>
                            {report.issue_references.map((issue: IssueReference) => (
                                <div key={issue.id} className="px-4 py-3 flex flex-col gap-y-1.5">
                                    <div className="flex items-center gap-x-2 flex-wrap">
                                        <LemonTag
                                            type={
                                                issue.status === 'resolved'
                                                    ? 'success'
                                                    : issue.status === 'pending_release'
                                                      ? 'warning'
                                                      : issue.status === 'archived' || issue.status === 'suppressed'
                                                        ? 'muted'
                                                        : 'danger'
                                            }
                                            size="small"
                                        >
                                            {issue.status}
                                        </LemonTag>
                                        <span className="text-sm font-medium flex-1 truncate">{issue.name}</span>
                                        <span className="text-xs text-secondary tabular-nums">
                                            {issue.occurrences.toLocaleString()} events
                                        </span>
                                        <span className="text-xs text-muted tabular-nums">
                                            {issue.users_affected.toLocaleString()} users
                                        </span>
                                    </div>
                                    {issue.sample_message && (
                                        <span className="text-xs text-secondary font-mono truncate">
                                            {issue.sample_message}
                                        </span>
                                    )}
                                    <span
                                        className="text-xs text-muted truncate"
                                        title={issue.matched_terms.join(', ')}
                                    >
                                        via {issue.matched_terms.slice(0, 3).join(', ')}
                                        {issue.matched_terms.length > 3 ? ` +${issue.matched_terms.length - 3}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {hasFlags && (
                        <>
                            <div className="px-4 py-3">
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    Per-flag reach · last {report.lookback_days} days
                                </span>
                            </div>
                            {report.per_flag_reach.map((flag: FlagReach) => (
                                <div key={flag.key} className="px-4 py-3 flex items-center gap-x-3">
                                    <span className="text-sm flex-1 font-mono truncate">{flag.key}</span>
                                    {flag.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {flag.has_data ? (
                                        flag.is_server_side ? (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {flag.call_count.toLocaleString()} evaluations
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {flag.users_affected.toLocaleString()} identities
                                                </span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {flag.users_affected.toLocaleString()} users
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {flag.call_count.toLocaleString()} evaluations
                                                </span>
                                            </>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                </div>
                            ))}
                        </>
                    )}

                    {hasEvents && (
                        <>
                            <div className="px-4 py-3">
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    Per-event reach · last {report.lookback_days} days
                                </span>
                            </div>
                            {report.per_event_reach.map((evt: EventReach) => (
                                <div key={evt.name} className="px-4 py-3 flex items-center gap-x-3">
                                    <span className="text-sm flex-1 font-mono truncate">{evt.name}</span>
                                    {evt.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {evt.has_data ? (
                                        evt.is_server_side ? (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {evt.call_count.toLocaleString()} fires
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {evt.users_affected.toLocaleString()} identities
                                                </span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {evt.users_affected.toLocaleString()} users
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {evt.call_count.toLocaleString()} fires
                                                </span>
                                            </>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                </div>
                            ))}
                        </>
                    )}

                    {hasRelated && (
                        <>
                            <div className="px-4 py-3">
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    Related signals · by filename match
                                </span>
                            </div>
                            <div className="px-4 -mt-1 pb-2">
                                <span className="text-xs text-muted">
                                    Not literally referenced in this PR, but they share names with files you touched.
                                    Worth a glance.
                                </span>
                            </div>
                            {report.related_signals.map((sig: RelatedSignal) => (
                                <div key={`${sig.kind}-${sig.key}`} className="px-4 py-3 flex items-center gap-x-3">
                                    <LemonTag type="muted" size="small">
                                        {sig.kind}
                                    </LemonTag>
                                    <span className="text-sm flex-1 font-mono truncate">{sig.key}</span>
                                    {sig.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {sig.has_data ? (
                                        sig.is_server_side ? (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {sig.call_count.toLocaleString()}{' '}
                                                {sig.kind === 'flag' ? 'evaluations' : 'fires'}
                                            </span>
                                        ) : (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {sig.users_affected.toLocaleString()} users
                                            </span>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                    <span
                                        className="text-xs text-muted truncate max-w-[30%]"
                                        title={sig.matched_tokens.join(', ')}
                                    >
                                        via {sig.matched_tokens.slice(0, 2).join(', ')}
                                        {sig.matched_tokens.length > 2 ? ` +${sig.matched_tokens.length - 2}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {hasFlags && report.flag_references.some((r: FlagReference) => r.key.startsWith('const:')) && (
                        <div className="px-4 py-3">
                            <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                Unresolved references
                            </span>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                {report.flag_references
                                    .filter((r: FlagReference) => r.key.startsWith('const:'))
                                    .map((r: FlagReference) => (
                                        <LemonTag key={r.key} type="muted" size="small">
                                            {r.key}
                                        </LemonTag>
                                    ))}
                            </div>
                        </div>
                    )}

                    {report.notes.length > 0 && (
                        <div className="px-4 py-3 flex flex-col gap-y-1.5">
                            {report.notes.map((note: string, idx: number) => (
                                <span key={idx} className="text-xs text-secondary">
                                    · {note}
                                </span>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

function diffLineClass(line: string): string {
    if (line.startsWith('+++') || line.startsWith('---')) {
        return 'text-muted font-bold'
    }
    if (line.startsWith('@@')) {
        return 'text-link bg-fill-highlight-50'
    }
    if (line.startsWith('diff --git')) {
        return 'text-secondary font-bold mt-2'
    }
    if (line.startsWith('+')) {
        return 'text-success bg-success-highlight'
    }
    if (line.startsWith('-')) {
        return 'text-danger bg-danger-highlight'
    }
    return 'text-primary'
}

function DiffWidget({ owner, name, number }: GitHogPRImpactLogicProps): JSX.Element {
    const logic = gitHogPRDiffLogic({ owner, name, number })
    const { diff, diffLoading } = useValues(logic)

    const lines = diff ? diff.split('\n') : []
    const stats = lines.reduce(
        (acc: { added: number; removed: number }, line: string) => {
            if (line.startsWith('+') && !line.startsWith('+++')) {
                acc.added += 1
            } else if (line.startsWith('-') && !line.startsWith('---')) {
                acc.removed += 1
            }
            return acc
        },
        { added: 0, removed: 0 }
    )

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-x-3 flex-wrap">
                <span className="font-semibold text-sm flex items-center gap-x-2">
                    <IconCode className="size-4 text-secondary" />
                    Diff
                </span>
                {!diffLoading && diff && (
                    <span className="text-xs text-secondary tabular-nums">
                        <span className="text-success">+{stats.added.toLocaleString()}</span>
                        {' / '}
                        <span className="text-danger">-{stats.removed.toLocaleString()}</span>
                    </span>
                )}
            </div>

            {diffLoading && (
                <div className="px-4 py-6 flex items-center justify-center gap-x-2 text-secondary text-sm">
                    <Spinner />
                    Fetching diff…
                </div>
            )}

            {!diffLoading && !diff && (
                <div className="px-4 py-6 text-sm text-secondary text-center">No diff available for this PR.</div>
            )}

            {!diffLoading && diff && (
                <div className="font-mono text-xs leading-relaxed overflow-x-auto max-h-[600px] overflow-y-auto">
                    {lines.map((line: string, idx: number) => (
                        <div key={idx} className={`px-4 whitespace-pre ${diffLineClass(line)}`}>
                            {line || ' '}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

const WIDGET_COMPONENTS: Record<WidgetType, (props: GitHogPRImpactLogicProps) => JSX.Element> = {
    conversation: () => <ConversationWidget />,
    diff: DiffWidget,
    stats: () => <StatsWidget />,
    reviewers: () => <ReviewersWidget />,
    files: () => <FilesWidget />,
    impact: ImpactWidget,
}

// ─── Scene ───────────────────────────────────────────────────────────────────

export function GitHogPRReviewScene({ owner, name, number }: GitHogPRImpactLogicProps): JSX.Element {
    const pr = SAMPLE_PR
    const prProps: GitHogPRImpactLogicProps = { owner, name, number }
    const [widgets, setWidgets] = useState<WidgetType[]>([])

    const addWidget = (type: WidgetType): void => setWidgets((prev) => [...prev, type])
    const removeWidget = (type: WidgetType): void => setWidgets((prev) => prev.filter((w) => w !== type))

    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))

    const mainWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'main')
    const sideWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'side')
    const hasSide = sideWidgets.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name={`#${number} ${pr.title}`}
                resourceType={{ type: 'githog' }}
                actions={
                    <LemonMenu
                        items={available.map((key) => ({
                            label: WIDGET_DEFS[key].label,
                            onClick: () => addWidget(key),
                        }))}
                        closeParentPopoverOnClickInside
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            disabledReason={available.length === 0 ? 'All widgets are already visible' : undefined}
                            size="small"
                        >
                            Add widget
                        </LemonButton>
                    </LemonMenu>
                }
            />

            {/* Minimal PR metadata — no card, just inline tags */}
            <div className="flex items-center gap-x-3 flex-wrap text-sm -mt-2">
                <LemonTag type="success" size="small">
                    Open
                </LemonTag>
                <span className="text-secondary flex items-center gap-x-1">
                    <IconGitBranch className="size-3.5" />
                    {pr.sourceBranch}
                    <span className="text-muted mx-0.5">→</span>
                    {pr.targetBranch}
                </span>
                <span className="text-muted">·</span>
                <span className="text-secondary">
                    {pr.author} · {pr.createdAt}
                </span>
            </div>

            {/* Widget area */}
            {widgets.length === 0 ? (
                <div className="border-2 border-dashed rounded-lg p-16 flex flex-col items-center gap-3 text-center mt-4">
                    <p className="text-secondary text-sm my-0">Add widgets to build your review workspace</p>
                    <LemonMenu
                        items={available.map((key) => ({
                            label: WIDGET_DEFS[key].label,
                            onClick: () => addWidget(key),
                        }))}
                        closeParentPopoverOnClickInside
                    >
                        <LemonButton type="primary" icon={<IconPlus />} size="small">
                            Add widget
                        </LemonButton>
                    </LemonMenu>
                </div>
            ) : (
                <div className={`flex gap-4 items-start mt-2 ${!hasSide ? '' : ''}`}>
                    {/* Main column */}
                    {(mainWidgets.length > 0 || !hasSide) && (
                        <div className="flex flex-col gap-y-4 flex-1 min-w-0">
                            {mainWidgets.map((type) => {
                                const Widget = WIDGET_COMPONENTS[type]
                                return (
                                    <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                        <Widget {...prProps} />
                                    </WidgetShell>
                                )
                            })}
                        </div>
                    )}

                    {/* Side column */}
                    {hasSide && (
                        <div className="flex flex-col gap-y-4 w-72 shrink-0">
                            {sideWidgets.map((type) => {
                                const Widget = WIDGET_COMPONENTS[type]
                                return (
                                    <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                        <Widget {...prProps} />
                                    </WidgetShell>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}
        </SceneContent>
    )
}

export default GitHogPRReviewScene
