import { useActions, useValues } from 'kea'
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
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    GitHogDataFlowStep,
    GitHogPullRequestDataFlowLogicProps,
    gitHogPullRequestDataFlowLogic,
} from './gitHogPullRequestDataFlowLogic'
import { gitHogPullRequestDetailLogic } from './gitHogPullRequestDetailLogic'

export const scene: SceneExport<GitHogPullRequestDataFlowLogicProps> = {
    component: GitHogPRReviewScene,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: Number(number ?? 0),
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

type WidgetType = 'conversation' | 'stats' | 'files' | 'reviewers' | 'dataFlow'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; column: 'main' | 'side' }> = {
    conversation: { label: 'Conversation', description: 'Comments and review discussion', column: 'main' },
    files: { label: 'Files changed', description: 'Modified files with line counts', column: 'main' },
    dataFlow: {
        label: 'Data flow',
        description: 'AI-generated execution flow before vs after',
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

const WIDGET_COMPONENTS: Record<WidgetType, () => JSX.Element> = {
    conversation: ConversationWidget,
    stats: StatsWidget,
    reviewers: ReviewersWidget,
    files: FilesWidget,
    // dataFlow is rendered specially because it needs PR props (owner/name/number);
    // see the inline branch in the scene render.
    dataFlow: () => <></>,
}

// ─── Scene ───────────────────────────────────────────────────────────────────

export function GitHogPRReviewScene({ owner, name, number }: GitHogPullRequestDataFlowLogicProps): JSX.Element {
    const { pullRequest, pullRequestLoading } = useValues(gitHogPullRequestDetailLogic({ owner, name, number }))
    const [widgets, setWidgets] = useState<WidgetType[]>([])
    const renderWidget = (type: WidgetType): JSX.Element => {
        if (type === 'dataFlow') {
            return <DataFlowWidgetForPR owner={owner} name={name} number={number} />
        }
        const Widget = WIDGET_COMPONENTS[type]
        return <Widget />
    }

    const addWidget = (type: WidgetType): void => setWidgets((prev) => [...prev, type])
    const removeWidget = (type: WidgetType): void => setWidgets((prev) => prev.filter((w) => w !== type))

    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))

    const mainWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'main')
    const sideWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'side')
    const hasSide = sideWidgets.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name={
                    pullRequest
                        ? `#${pullRequest.number} ${pullRequest.title}`
                        : pullRequestLoading
                          ? `#${number} Loading…`
                          : `#${number}`
                }
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
                    <span className="text-muted">{pullRequestLoading ? 'Loading PR metadata…' : '—'}</span>
                )}
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
                            {mainWidgets.map((type) => (
                                <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                    {renderWidget(type)}
                                </WidgetShell>
                            ))}
                        </div>
                    )}

                    {/* Side column */}
                    {hasSide && (
                        <div className="flex flex-col gap-y-4 w-72 shrink-0">
                            {sideWidgets.map((type) => (
                                <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                    {renderWidget(type)}
                                </WidgetShell>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </SceneContent>
    )
}

export default GitHogPRReviewScene
