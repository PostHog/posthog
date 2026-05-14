import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCode, IconGitBranch, IconPlus, IconRefresh, IconX } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import MermaidDiagram from 'lib/lemon-ui/LemonMarkdown/MermaidDiagram'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

import {
    GitHogPRReviewLogicProps,
    GitHogPullRequestDetail,
    GitHogPullRequestFile,
    gitHogPRReviewLogic,
} from '../gitHogPRReviewLogic'
import {
    GitHogDataFlowStep,
    GitHogPullRequestDataFlowLogicProps,
    gitHogPullRequestDataFlowLogic,
} from '../gitHogPullRequestDataFlowLogic'
import { gitHogPullRequestDetailLogic } from '../gitHogPullRequestDetailLogic'
import {
    GitHogPullRequestRiskScoreLogicProps,
    GitHogRiskLevel,
    gitHogPullRequestRiskScoreLogic,
} from '../gitHogPullRequestRiskScoreLogic'
import { GitHogAgentChatWidget, PRChatContext } from './GitHogAgentChatWidget'

// ─── Mock data ────────────────────────────────────────────────────────────────
//
// Comments and reviewers aren't yet exposed by the githog backend; keep mocks
// so the scene renders, but every widget that *can* use real data does.

const SAMPLE_REVIEWERS = [
    { name: 'Marcus Webb', initials: 'MW', status: 'changes_requested' as const },
    { name: 'Priya Kapoor', initials: 'PK', status: 'approved' as const },
    { name: 'James Liu', initials: 'JL', status: 'pending' as const },
]

const SAMPLE_COMMENTS = [
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
]

// ─── Widget registry ─────────────────────────────────────────────────────────

// Note: the agent chat and risk assessment are pinned and not part of this
// menu — they're always visible at the right and at the top respectively.
type WidgetType = 'conversation' | 'stats' | 'files' | 'reviewers' | 'dataFlow'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string }> = {
    dataFlow: { label: 'Data flow', description: 'AI-generated execution flow before vs after' },
    files: { label: 'Files changed', description: 'Modified files with line counts' },
    stats: { label: 'Stats', description: 'Additions, deletions, and commits' },
    conversation: { label: 'Conversation', description: 'Comments and review discussion' },
    reviewers: { label: 'Reviewers', description: 'Review status per reviewer' },
}

const DEFAULT_WIDGETS: WidgetType[] = ['dataFlow', 'files', 'stats']

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
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Conversation</span>
                <span className="text-xs text-secondary">{SAMPLE_COMMENTS.length} comments (mock)</span>
            </div>
            {SAMPLE_COMMENTS.map((c) => (
                <div key={c.id} className="px-4 py-4 flex gap-x-3">
                    <Avatar initials={c.initials} />
                    <div className="flex flex-col gap-y-1.5 flex-1 min-w-0">
                        <div className="flex items-center gap-x-2 flex-wrap">
                            <span className="font-semibold text-sm">{c.author}</span>
                            <span className="text-xs text-secondary">{c.timestamp}</span>
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

function StatsWidget({ pr }: { pr: GitHogPullRequestDetail }): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3">
                <span className="font-semibold text-sm">Stats</span>
            </div>
            <div className="grid grid-cols-2 divide-x divide-y divide-border">
                {[
                    { label: 'Additions', value: `+${pr.additions}`, className: 'text-success' },
                    { label: 'Deletions', value: `-${pr.deletions}`, className: 'text-danger' },
                    { label: 'Files', value: pr.changed_files, className: '' },
                    { label: 'Commits', value: pr.commits, className: '' },
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
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Reviewers</span>
                <span className="text-xs text-secondary">mock</span>
            </div>
            <div className="px-4 py-3 flex flex-col gap-y-3">
                {SAMPLE_REVIEWERS.map((r) => (
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

function FilesWidget({ files }: { files: GitHogPullRequestFile[] }): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Files changed</span>
                <span className="text-xs text-secondary">{files.length} files</span>
            </div>
            {files.map((f) => (
                <div key={f.filename} className="px-4 py-2.5 flex items-center gap-x-3">
                    <IconCode className="size-3.5 text-muted shrink-0" />
                    <span className="text-sm flex-1 font-mono truncate">{f.filename}</span>
                    {f.status === 'added' && (
                        <LemonTag type="success" size="small">
                            New
                        </LemonTag>
                    )}
                    {f.status === 'removed' && (
                        <LemonTag type="danger" size="small">
                            Removed
                        </LemonTag>
                    )}
                    <span className="text-xs text-success shrink-0">+{f.additions}</span>
                    <span className="text-xs text-danger shrink-0">-{f.deletions}</span>
                </div>
            ))}
        </div>
    )
}

function AgentWidget({
    owner,
    repo,
    pr,
    files,
    diff,
}: {
    owner: string
    repo: string
    pr: GitHogPullRequestDetail
    files: GitHogPullRequestFile[]
    diff: string | null
}): JSX.Element {
    const context: PRChatContext = { owner, repo, pr, files, diff }
    return <GitHogAgentChatWidget context={context} />
}

function StepList({ steps, emptyLabel }: { steps: GitHogDataFlowStep[]; emptyLabel: string }): JSX.Element {
    if (steps.length === 0) {
        return <p className="text-secondary text-sm italic my-0">{emptyLabel}</p>
    }
    return (
        <ol className="flex flex-col gap-2 my-0 pl-5">
            {steps.map((step, idx) => (
                <li key={`${step.title}-${idx}`} className="text-sm">
                    <div className="font-semibold">{step.title}</div>
                    {step.file && <div className="font-mono text-xs text-muted">{step.file}</div>}
                    {step.detail && <div className="text-sm text-secondary">{step.detail}</div>}
                </li>
            ))}
        </ol>
    )
}

function DataFlowWidgetForPR({ owner, name, number }: GitHogPullRequestDataFlowLogicProps): JSX.Element {
    const logic = gitHogPullRequestDataFlowLogic({ owner, name, number })
    const { dataFlow, dataFlowLoading, view } = useValues(logic)
    const { setView, refreshDataFlow } = useActions(logic)

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-2">
                <span className="font-semibold text-sm">Data flow</span>
                <div className="flex items-center gap-2">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={view}
                        onChange={(v) => setView(v)}
                        options={[
                            { value: 'mermaid', label: 'Diagram' },
                            { value: 'steps', label: 'Steps' },
                        ]}
                    />
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={dataFlowLoading}
                        onClick={() => refreshDataFlow()}
                        tooltip="Force-recompute via LLM"
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>
            <div className="px-4 py-4 flex flex-col gap-3">
                {dataFlowLoading && !dataFlow ? (
                    <>
                        <LemonSkeleton className="h-4 w-3/4" />
                        <LemonSkeleton className="h-32 w-full" />
                        <LemonSkeleton className="h-32 w-full" />
                    </>
                ) : !dataFlow ? (
                    <p className="text-secondary text-sm my-0">No flow available yet. Click Refresh to generate one.</p>
                ) : (
                    <>
                        {dataFlow.summary && (
                            <p className="text-sm text-secondary my-0 leading-relaxed">{dataFlow.summary}</p>
                        )}
                        {dataFlow.truncated && (
                            <LemonTag type="warning" size="small">
                                Truncated — files were too large for full context, flow inferred from diff
                            </LemonTag>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="flex flex-col gap-2 min-w-0">
                                <div className="text-xs uppercase tracking-wide text-muted">Before</div>
                                {view === 'mermaid' ? (
                                    dataFlow.mermaid_before ? (
                                        <MermaidDiagram code={dataFlow.mermaid_before} />
                                    ) : (
                                        <p className="text-sm text-secondary italic my-0">No prior flow.</p>
                                    )
                                ) : (
                                    <StepList steps={dataFlow.steps_before} emptyLabel="No prior flow." />
                                )}
                            </div>
                            <div className="flex flex-col gap-2 min-w-0">
                                <div className="text-xs uppercase tracking-wide text-muted">After</div>
                                {view === 'mermaid' ? (
                                    dataFlow.mermaid_after ? (
                                        <MermaidDiagram code={dataFlow.mermaid_after} />
                                    ) : (
                                        <p className="text-sm text-secondary italic my-0">No new flow.</p>
                                    )
                                ) : (
                                    <StepList steps={dataFlow.steps_after} emptyLabel="No new flow." />
                                )}
                            </div>
                        </div>
                        <div className="text-xs text-muted">
                            head {dataFlow.head_sha.slice(0, 7)} · {dataFlow.cached ? 'cached' : 'freshly computed'}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

const RISK_LEVEL_STYLES: Record<
    GitHogRiskLevel,
    { tag: 'success' | 'warning' | 'danger' | 'default'; bar: string; text: string; label: string }
> = {
    low: { tag: 'success', bar: 'bg-success', text: 'text-success', label: 'Safe' },
    moderate: { tag: 'warning', bar: 'bg-warning', text: 'text-warning', label: 'Medium' },
    high: { tag: 'danger', bar: 'bg-danger', text: 'text-danger', label: 'High risk' },
    critical: { tag: 'danger', bar: 'bg-danger', text: 'text-danger', label: 'High risk' },
}

function FactorBar({ value }: { value: number }): JSX.Element {
    const pct = Math.max(0, Math.min(100, value))
    const color = pct >= 75 ? 'bg-danger' : pct >= 50 ? 'bg-warning' : pct >= 25 ? 'bg-muted' : 'bg-success'
    return (
        <div className="w-full h-1.5 rounded-full bg-fill-highlight-100 overflow-hidden">
            <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
        </div>
    )
}

function RiskAssessmentBanner({ owner, name, number }: GitHogPullRequestRiskScoreLogicProps): JSX.Element {
    // Compact pinned banner — no refresh, no close. Shows just the level and a
    // micro-grid of factors so the reviewer scans risk at a glance.
    const logic = gitHogPullRequestRiskScoreLogic({ owner, name, number })
    const { riskScore, riskScoreLoading } = useValues(logic)

    const styles = (riskScore && RISK_LEVEL_STYLES[riskScore.level]) || RISK_LEVEL_STYLES.moderate
    const factors = riskScore?.factors ?? []

    return (
        <LemonCard hoverEffect={false} className="p-0 overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
                <span className="font-semibold text-sm shrink-0">Risk</span>
                {riskScoreLoading && !riskScore ? (
                    <LemonSkeleton className="h-5 w-20 rounded-full" />
                ) : !riskScore ? (
                    <span className="text-secondary text-xs">No assessment yet</span>
                ) : (
                    <>
                        <LemonTag type={styles.tag} size="small">
                            <span className={`font-semibold ${styles.text}`}>{styles.label}</span>
                        </LemonTag>
                        <div className="flex items-center gap-3 flex-1 min-w-0">
                            {factors.map((f) => (
                                <div key={f.key} className="flex flex-col gap-0.5 min-w-0 flex-1" title={f.detail}>
                                    <span className="text-xs text-secondary truncate">{f.label}</span>
                                    <FactorBar value={f.score} />
                                </div>
                            ))}
                        </div>
                    </>
                )}
            </div>
        </LemonCard>
    )
}

// ─── Public workspace component ──────────────────────────────────────────────

export function GitHogPRWorkspace({ owner, name, number }: GitHogPRReviewLogicProps): JSX.Element {
    return (
        <BindLogic logic={gitHogPRReviewLogic} props={{ owner, name, number }}>
            <GitHogPRWorkspaceInner owner={owner} repoName={name} number={number} />
        </BindLogic>
    )
}

function GitHogPRWorkspaceInner({
    owner,
    repoName,
    number,
}: {
    owner: string
    repoName: string
    number: number
}): JSX.Element {
    const { prDetail, prDetailLoading } = useValues(gitHogPRReviewLogic)
    const { pullRequest, pullRequestLoading } = useValues(
        gitHogPullRequestDetailLogic({ owner, name: repoName, number })
    )
    const [widgets, setWidgets] = useState<WidgetType[]>(DEFAULT_WIDGETS)

    const addWidget = (type: WidgetType): void => setWidgets((prev) => [...prev, type])
    const removeWidget = (type: WidgetType): void => setWidgets((prev) => prev.filter((w) => w !== type))

    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))

    if (prDetailLoading && !prDetail) {
        return (
            <div className="flex items-center justify-center py-16">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (!prDetail) {
        return (
            <p className="text-secondary text-sm">
                Could not load this pull request. Check that the team's GitHub integration has access to{' '}
                <code>
                    {owner}/{repoName}
                </code>
                .
            </p>
        )
    }

    const pr = prDetail.pull_request
    const renderWidget = (type: WidgetType): JSX.Element => {
        switch (type) {
            case 'conversation':
                return <ConversationWidget />
            case 'files':
                return <FilesWidget files={prDetail.files} />
            case 'dataFlow':
                return <DataFlowWidgetForPR owner={owner} name={repoName} number={number} />
            case 'stats':
                return <StatsWidget pr={pr} />
            case 'reviewers':
                return <ReviewersWidget />
        }
    }

    return (
        <div className="flex flex-col gap-y-3">
            {/* Compact PR header — no SceneTitleSection here; the inbox owns the page title */}
            <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-y-1 min-w-0">
                    <h2 className="text-lg font-semibold my-0 truncate">
                        <span className="text-muted font-mono mr-2">#{pr.number}</span>
                        {pr.title}
                    </h2>
                    <div className="flex items-center gap-x-3 flex-wrap text-sm">
                        {pullRequest ? (
                            <>
                                <LemonTag
                                    type={
                                        pullRequest.merged_at
                                            ? 'completion'
                                            : pullRequest.state === 'open'
                                              ? pullRequest.draft
                                                  ? 'default'
                                                  : 'success'
                                              : 'danger'
                                    }
                                    size="small"
                                >
                                    {pullRequest.merged_at
                                        ? 'Merged'
                                        : pullRequest.draft
                                          ? 'Draft'
                                          : pullRequest.state === 'open'
                                            ? 'Open'
                                            : 'Closed'}
                                </LemonTag>
                                <span className="text-secondary flex items-center gap-x-1">
                                    <IconGitBranch className="size-3.5" />
                                    {pullRequest.head_branch}
                                    <span className="text-muted mx-0.5">→</span>
                                    {pullRequest.base_branch}
                                </span>
                                <span className="text-muted">·</span>
                                <span className="text-secondary flex items-center gap-x-1">
                                    {pullRequest.author || 'unknown'}
                                    {pullRequest.created_at && (
                                        <>
                                            <span className="text-muted mx-1">·</span>
                                            <TZLabel time={pullRequest.created_at} />
                                        </>
                                    )}
                                </span>
                            </>
                        ) : (
                            <>
                                <LemonTag type={pr.state === 'open' ? 'success' : 'default'} size="small">
                                    {pr.draft ? 'Draft' : pr.state}
                                </LemonTag>
                                <span className="text-secondary flex items-center gap-x-1">
                                    <IconGitBranch className="size-3.5" />
                                    {pr.head_branch}
                                    <span className="text-muted mx-0.5">→</span>
                                    {pr.base_branch}
                                </span>
                                <span className="text-muted">·</span>
                                <span className="text-secondary">
                                    {pr.author || 'unknown'}
                                    {pullRequestLoading && <span className="text-muted ml-2">· loading…</span>}
                                </span>
                            </>
                        )}
                    </div>
                </div>
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
            </div>

            <div className="flex gap-4 items-start mt-2">
                {/* Main widget column — pinned risk banner on top, then stackable widgets */}
                <div className="flex flex-col gap-y-4 flex-1 min-w-0">
                    <RiskAssessmentBanner owner={owner} name={repoName} number={number} />

                    {widgets.length === 0 ? (
                        <div className="border-2 border-dashed rounded-lg p-16 flex flex-col items-center gap-3 text-center">
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
                        widgets.map((type) => (
                            <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                {renderWidget(type)}
                            </WidgetShell>
                        ))
                    )}
                </div>

                {/* Sticky chat column — viewport-bound height. The subtraction
                    accounts for the top nav + SceneTitleSection + workspace
                    header above this aside, plus a small bottom buffer, so the
                    chat is fully visible both at the initial scroll position
                    and once the panel sticks. */}
                <aside className="w-80 shrink-0 sticky top-4 self-start min-h-[400px] h-[calc(100dvh-16rem)] max-h-[calc(100dvh-2rem)]">
                    <LemonCard hoverEffect={false} className="p-0 overflow-hidden h-full flex flex-col">
                        <AgentWidget
                            owner={owner}
                            repo={repoName}
                            pr={pr}
                            files={prDetail.files}
                            diff={prDetail.diff}
                        />
                    </LemonCard>
                </aside>
            </div>
        </div>
    )
}
