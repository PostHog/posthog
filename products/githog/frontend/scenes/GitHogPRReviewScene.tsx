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
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    GitHogPRReviewLogicProps,
    GitHogPullRequestDetail,
    GitHogPullRequestFile,
    gitHogPRReviewLogic,
} from './gitHogPRReviewLogic'
import {
    GitHogDataFlowStep,
    GitHogPullRequestDataFlowLogicProps,
    gitHogPullRequestDataFlowLogic,
} from './gitHogPullRequestDataFlowLogic'
import { gitHogPullRequestDetailLogic } from './gitHogPullRequestDetailLogic'
import { GitHogAgentChatWidget, PRChatContext } from './widgets/GitHogAgentChatWidget'

export const scene: SceneExport<GitHogPRReviewLogicProps> = {
    component: GitHogPRReviewScene,
    logic: gitHogPRReviewLogic,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: Number(number ?? 0),
    }),
}

// ─── Mock data for widgets we don't yet back with a real API ──────────────────
//
// Comments and reviewers aren't yet exposed by the githog backend. We keep
// mocks for those widgets so the scene renders, but every widget that *can*
// use real data (header, files, stats, agent, data flow) does.

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

type WidgetType = 'conversation' | 'stats' | 'files' | 'reviewers' | 'agent' | 'dataFlow'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; column: 'main' | 'side' }> = {
    conversation: { label: 'Conversation', description: 'Comments and review discussion', column: 'main' },
    files: { label: 'Files changed', description: 'Modified files with line counts', column: 'main' },
    agent: { label: 'Ask the agent', description: 'Chat with an AI agent about this PR', column: 'main' },
    dataFlow: { label: 'Data flow', description: 'AI-generated execution flow before vs after', column: 'main' },
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

// ─── Scene ───────────────────────────────────────────────────────────────────

export function GitHogPRReviewScene({ owner, name, number }: GitHogPRReviewLogicProps): JSX.Element {
    return (
        <BindLogic logic={gitHogPRReviewLogic} props={{ owner, name, number }}>
            <GitHogPRReviewSceneInner owner={owner} repoName={name} number={number} />
        </BindLogic>
    )
}

function GitHogPRReviewSceneInner({
    owner,
    repoName,
    number,
}: {
    owner: string
    repoName: string
    number: number
}): JSX.Element {
    // Two logics used in parallel:
    //  - ``gitHogPRReviewLogic`` (HEAD): PR meta + files + unified diff. Backs the
    //    stats/files/agent widgets that need the diff.
    //  - ``gitHogPullRequestDetailLogic`` (incoming): lighter PR metadata
    //    with ``merged_at``, ``author_avatar_url``, etc., used for the header
    //    strip's merged/draft/closed tag logic. Slight duplication is the
    //    hackathon-acceptable tax for keeping both branches' UX intact.
    const { prDetail, prDetailLoading } = useValues(gitHogPRReviewLogic)
    const { pullRequest, pullRequestLoading } = useValues(gitHogPullRequestDetailLogic({ owner, name: repoName, number }))
    const [widgets, setWidgets] = useState<WidgetType[]>([])

    const addWidget = (type: WidgetType): void => setWidgets((prev) => [...prev, type])
    const removeWidget = (type: WidgetType): void => setWidgets((prev) => prev.filter((w) => w !== type))

    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))

    const mainWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'main')
    const sideWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'side')
    const hasSide = sideWidgets.length > 0

    if (prDetailLoading && !prDetail) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center py-16">
                    <Spinner className="text-2xl" />
                </div>
            </SceneContent>
        )
    }

    if (!prDetail) {
        return (
            <SceneContent>
                <SceneTitleSection name={`#${number} in ${owner}/${repoName}`} resourceType={{ type: 'githog' }} />
                <p className="text-secondary text-sm">
                    Could not load this pull request. Check that the team's GitHub integration has access to{' '}
                    <code>
                        {owner}/{repoName}
                    </code>
                    .
                </p>
            </SceneContent>
        )
    }

    const pr = prDetail.pull_request
    const renderWidget = (type: WidgetType): JSX.Element => {
        switch (type) {
            case 'conversation':
                return <ConversationWidget />
            case 'files':
                return <FilesWidget files={prDetail.files} />
            case 'agent':
                return <AgentWidget owner={owner} repo={repoName} pr={pr} files={prDetail.files} diff={prDetail.diff} />
            case 'dataFlow':
                return <DataFlowWidgetForPR owner={owner} name={repoName} number={number} />
            case 'stats':
                return <StatsWidget pr={pr} />
            case 'reviewers':
                return <ReviewersWidget />
        }
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={`#${pr.number} ${pr.title}`}
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

            {/* PR metadata strip — prefers the richer "detail" logic shape (it
                knows about merged_at/draft/closed) and falls back to the diff
                logic's PR shape while the detail load is in flight. */}
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
                            {owner}/{repoName} · {pullRequest.author || 'unknown'}
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
                            {owner}/{repoName} · {pr.author || 'unknown'}
                            {pullRequestLoading && <span className="text-muted ml-2">·  loading…</span>}
                        </span>
                    </>
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
                <div className="flex gap-4 items-start mt-2">
                    {(mainWidgets.length > 0 || !hasSide) && (
                        <div className="flex flex-col gap-y-4 flex-1 min-w-0">
                            {mainWidgets.map((type) => (
                                <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                    {renderWidget(type)}
                                </WidgetShell>
                            ))}
                        </div>
                    )}

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
