// Vendored from react-grid-layout/css/styles.css — the package's export map
// is not reachable from products/* under our Vite workspace setup, so we keep
// a local copy. Provides .react-grid-item / resize-handle styling.
import './GitHogPRWorkspace.css'

import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'
import { Layout, Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'

import {
    IconCheck,
    IconCode,
    IconDrag,
    IconGitBranch,
    IconGithub,
    IconPlus,
    IconRefresh,
    IconSend,
    IconX,
} from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DataFlowGraph, DiffStatus, computeFlowDiff } from '../DataFlowGraph'
import {
    GitHogLayoutItem,
    GitHogPRLayoutLogicProps,
    GitHogWidgetType,
    gitHogPRLayoutLogic,
} from '../gitHogPRLayoutLogic'
import {
    GitHogPRReviewLogicProps,
    GitHogPullRequestDetail,
    GitHogPullRequestFile,
    gitHogPRReviewLogic,
} from '../gitHogPRReviewLogic'
import {
    GitHogDataFlowStep,
    GitHogFlowNode,
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

// ─── Widget registry ─────────────────────────────────────────────────────────

type WidgetType = GitHogWidgetType

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; defaultW: number; defaultH: number }> = {
    conversation: { label: 'Conversation', description: 'Comments and review discussion', defaultW: 8, defaultH: 5 },
    files: { label: 'Files changed', description: 'Modified files with line counts', defaultW: 8, defaultH: 5 },
    agent: { label: 'Ask the agent', description: 'Chat with an AI agent about this PR', defaultW: 8, defaultH: 6 },
    dataFlow: {
        label: 'Data flow',
        description: 'AI-generated execution flow before vs after',
        defaultW: 8,
        defaultH: 7,
    },
    riskScore: {
        label: 'Risk assessment',
        description: 'Per-factor risk breakdown for this PR',
        defaultW: 4,
        defaultH: 5,
    },
    stats: { label: 'Stats', description: 'Additions, deletions, and commits', defaultW: 4, defaultH: 3 },
    reviewers: { label: 'Reviewers', description: 'Review status per reviewer', defaultW: 4, defaultH: 4 },
}

// Grid configuration shared with the persisted layout shape on the backend.
const GRID_COLS = 12
const GRID_ROW_HEIGHT = 60
const GRID_MARGIN: [number, number] = [12, 12]
const GRID_PADDING: [number, number] = [0, 0]

// ─── Sub-components ──────────────────────────────────────────────────────────

function initialsFromName(name: string): string {
    return name
        .split(/\s+/)
        .map((w) => w[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()
}

function Avatar({ initials, size = 'md' }: { initials: string; size?: 'sm' | 'md' }): JSX.Element {
    const cls = size === 'sm' ? 'size-7 text-xs' : 'size-8 text-sm'
    return (
        <div
            className={`${cls} rounded-full bg-fill-highlight-100 flex items-center justify-center font-semibold text-secondary shrink-0`}
        >
            {initials || '?'}
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

function WidgetShell({
    label,
    children,
    onRemove,
}: {
    label: string
    children: React.ReactNode
    onRemove: () => void
}): JSX.Element {
    // The chrome bar is a single intentional strip at the top: the drag
    // affordance fills the bar (entire strip is the grab target), and the
    // remove button is anchored to the right edge. Interactive children are
    // excluded from the drag via `dragConfig.cancel` so dragging and removing
    // never compete for the same pixels — unlike the previous overlay X, which
    // floated above content and intercepted clicks meant for the widget body.
    return (
        <LemonCard hoverEffect={false} className="p-0 overflow-hidden h-full w-full flex flex-col">
            <div className="relative group/widget-header flex items-stretch h-5 shrink-0 border-b border-border bg-fill-highlight-50 hover:bg-fill-highlight-100">
                <div
                    className="githog-widget-drag-handle flex-1 flex items-center justify-center cursor-grab active:cursor-grabbing"
                    aria-label={`Drag ${label}`}
                    role="button"
                >
                    <IconDrag className="size-3.5 text-muted" />
                </div>
                {/* Anchored to the right edge of the bar; never overlaps the widget body. */}
                <LemonButton
                    icon={<IconX />}
                    size="xsmall"
                    type="tertiary"
                    onClick={(e) => {
                        e.stopPropagation()
                        onRemove()
                    }}
                    tooltip="Remove widget"
                    aria-label={`Remove ${label}`}
                    className="!h-5 !min-h-0 !px-1 rounded-none opacity-0 group-hover/widget-header:opacity-100 focus-visible:opacity-100"
                />
            </div>
            <div className="flex-1 min-h-0 overflow-auto">{children}</div>
        </LemonCard>
    )
}

// ─── Individual widgets ───────────────────────────────────────────────────────

function ConversationWidget(): JSX.Element {
    const { messages, messagesLoading, draftMessage, submitting } = useValues(gitHogPRReviewLogic)
    const { setDraftMessage, submitMessage } = useActions(gitHogPRReviewLogic)

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            submitMessage()
        }
    }

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Conversation</span>
                {!messagesLoading && <span className="text-xs text-secondary">{messages.length} messages</span>}
            </div>

            {messagesLoading ? (
                <div className="px-4 py-4 flex flex-col gap-y-3">
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-1/2" />
                </div>
            ) : messages.length === 0 ? (
                <div className="px-4 py-8 text-center text-secondary text-sm">
                    No messages yet. Be the first to comment.
                </div>
            ) : (
                messages.map((m) => (
                    <div key={m.id} className="px-4 py-4 flex gap-x-3">
                        <Avatar initials={initialsFromName(m.author_name)} />
                        <div className="flex flex-col gap-y-1 flex-1 min-w-0">
                            <div className="flex items-center gap-x-2">
                                <span className="font-semibold text-sm">{m.author_name}</span>
                                <span className="text-xs text-secondary">
                                    {new Date(m.created_at).toLocaleString()}
                                </span>
                            </div>
                            <p className="text-sm text-primary my-0 leading-relaxed whitespace-pre-wrap">{m.body}</p>
                        </div>
                    </div>
                ))
            )}

            <div className="px-4 py-3 flex flex-col gap-y-2">
                <LemonTextArea
                    value={draftMessage}
                    onChange={setDraftMessage}
                    onKeyDown={handleKeyDown}
                    placeholder="Leave a comment… (⌘ Enter to send)"
                    minRows={2}
                    maxRows={8}
                />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconSend />}
                        onClick={submitMessage}
                        loading={submitting}
                        disabledReason={!draftMessage.trim() ? 'Enter a message first' : undefined}
                    >
                        Send
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

function StatsWidget({ pr }: { pr: GitHogPullRequestDetail }): JSX.Element {
    const items: { label: string; value: string | number; className?: string }[] = [
        { label: 'Additions', value: `+${pr.additions}`, className: 'text-success' },
        { label: 'Deletions', value: `-${pr.deletions}`, className: 'text-danger' },
        { label: 'Files', value: pr.changed_files },
        { label: 'Commits', value: pr.commits },
    ]
    return (
        <div className="px-4 py-2.5 flex items-center gap-x-6 flex-wrap">
            <span className="font-semibold text-sm shrink-0">Stats</span>
            {items.map(({ label, value, className }) => (
                <div key={label} className="flex items-baseline gap-x-1.5">
                    <span className={`text-sm font-semibold tabular-nums ${className ?? ''}`}>{value}</span>
                    <span className="text-xs text-secondary">{label}</span>
                </div>
            ))}
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

function LegendDot({ color, label }: { color: string; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            <span
                className="inline-block size-2.5 rounded-sm border"
                style={{ background: color, borderColor: color }}
            />
            <span>{label}</span>
        </span>
    )
}

interface NodeDiffSelection {
    node: GitHogFlowNode
    diff: DiffStatus
    file?: GitHogPullRequestFile
}

function DataFlowWidgetForPR({
    owner,
    name,
    number,
    files,
}: GitHogPullRequestDataFlowLogicProps & { files: GitHogPullRequestFile[] }): JSX.Element {
    const logic = gitHogPullRequestDataFlowLogic({ owner, name, number })
    const { dataFlow, dataFlowLoading, view } = useValues(logic)
    const { setView, refreshDataFlow } = useActions(logic)
    const [selected, setSelected] = useState<NodeDiffSelection | null>(null)

    const diff = useMemo(() => {
        if (!dataFlow) {
            return null
        }
        return computeFlowDiff(dataFlow.flow_before, dataFlow.flow_after)
    }, [dataFlow])

    const filesByName = useMemo(() => {
        const m = new Map<string, GitHogPullRequestFile>()
        files.forEach((f) => m.set(f.filename, f))
        return m
    }, [files])

    const handleNodeClick = useCallback(
        (node: GitHogFlowNode, status: DiffStatus) => {
            // Kept = unchanged conceptually — nothing useful to show.
            if (status === 'kept') {
                return
            }
            const file = node.file ? filesByName.get(node.file) : undefined
            setSelected({ node, diff: status, file })
        },
        [filesByName]
    )

    const renderBody = (): JSX.Element => {
        if (dataFlowLoading && !dataFlow) {
            return (
                <>
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-64 w-full" />
                </>
            )
        }
        if (!dataFlow) {
            return <p className="text-secondary text-sm my-0">No flow available yet. Click Refresh to generate one.</p>
        }
        if (view === 'steps') {
            return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="flex flex-col gap-2 min-w-0">
                        <div className="text-xs uppercase tracking-wide text-muted">Before</div>
                        <StepList steps={dataFlow.steps_before} emptyLabel="No prior flow." />
                    </div>
                    <div className="flex flex-col gap-2 min-w-0">
                        <div className="text-xs uppercase tracking-wide text-muted">After</div>
                        <StepList steps={dataFlow.steps_after} emptyLabel="No new flow." />
                    </div>
                </div>
            )
        }
        if (view === 'graphs') {
            return (
                <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2 min-w-0">
                        <div className="text-xs uppercase tracking-wide text-muted">Before</div>
                        <DataFlowGraph graph={dataFlow.flow_before} heightClass="h-[24rem]" />
                    </div>
                    <div className="flex flex-col gap-2 min-w-0">
                        <div className="text-xs uppercase tracking-wide text-muted">After</div>
                        <DataFlowGraph
                            graph={dataFlow.flow_after}
                            nodeDiff={diff?.nodeDiff}
                            onNodeClick={handleNodeClick}
                            heightClass="h-[24rem]"
                        />
                    </div>
                </div>
            )
        }
        // diff
        if (!diff) {
            return <p className="text-secondary text-sm my-0">No diff available.</p>
        }
        return (
            <DataFlowGraph
                graph={diff.unionGraph}
                nodeDiff={diff.nodeDiff}
                edgeDiff={diff.edgeDiff}
                onNodeClick={handleNodeClick}
                heightClass="h-[32rem]"
            />
        )
    }

    const legend = (
        <div className="flex items-center gap-x-4 gap-y-1 text-xs text-muted flex-wrap">
            <span className="font-semibold uppercase tracking-wide text-[10px] opacity-70">Kinds</span>
            <LegendDot color="rgb(59,130,246)" label="Entry" />
            <LegendDot color="rgb(148,163,184)" label="Step" />
            <LegendDot color="rgb(168,85,247)" label="Side effect" />
            <LegendDot color="rgb(107,114,128)" label="Return" />
            {view === 'diff' && (
                <>
                    <span className="font-semibold uppercase tracking-wide text-[10px] opacity-70 ml-2">Diff</span>
                    <LegendDot color="rgb(34,197,94)" label="Added" />
                    <LegendDot color="rgb(239,68,68)" label="Removed" />
                    <LegendDot color="rgb(203,213,225)" label="Kept" />
                </>
            )}
        </div>
    )

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-2 flex-wrap">
                <span className="font-semibold text-sm">Data flow</span>
                <div className="flex items-center gap-2">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={view}
                        onChange={(v) => setView(v)}
                        options={[
                            { value: 'graphs', label: 'Before & After' },
                            { value: 'diff', label: 'Diff' },
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
                {/* Summary intentionally hidden in UI; still returned by the API for callers. */}
                {dataFlow?.truncated && (
                    <LemonTag type="warning" size="small">
                        Truncated — files were too large for full context, flow inferred from diff
                    </LemonTag>
                )}
                {dataFlow && view !== 'steps' && legend}
                {renderBody()}
                {dataFlow && (
                    <div className="text-xs text-muted">
                        head {dataFlow.head_sha.slice(0, 7)} · {dataFlow.cached ? 'cached' : 'freshly computed'} ·{' '}
                        {dataFlow.files_with_content}/{dataFlow.files_total} files with full content
                    </div>
                )}
            </div>
            <NodeDiffModal selection={selected} onClose={() => setSelected(null)} />
        </div>
    )
}

function NodeDiffModal({
    selection,
    onClose,
}: {
    selection: NodeDiffSelection | null
    onClose: () => void
}): JSX.Element {
    const isOpen = selection !== null
    const node = selection?.node
    const diff = selection?.diff
    const file = selection?.file
    const tagType = diff === 'added' ? 'success' : diff === 'removed' ? 'danger' : 'default'
    const tagLabel = diff === 'added' ? 'Added' : diff === 'removed' ? 'Removed' : 'Kept'
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={
                node ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <span>{node.label}</span>
                        <LemonTag type={tagType} size="small">
                            {tagLabel}
                        </LemonTag>
                    </div>
                ) : (
                    'Node detail'
                )
            }
            description={node?.detail || undefined}
            width={900}
        >
            {node && (
                <div className="flex flex-col gap-3">
                    {node.file && <div className="text-xs text-muted font-mono break-all">{node.file}</div>}
                    {file ? (
                        file.patch ? (
                            <div className="max-h-[60vh] overflow-auto">
                                <CodeSnippet language={Language.Diff} wrap>
                                    {file.patch}
                                </CodeSnippet>
                            </div>
                        ) : (
                            <p className="text-sm text-secondary italic my-0">
                                No patch available for this file ({file.status}).
                            </p>
                        )
                    ) : node.file ? (
                        <p className="text-sm text-secondary italic my-0">
                            This file isn't in the PR's changed files — the change may live in a referenced file.
                        </p>
                    ) : (
                        <p className="text-sm text-secondary italic my-0">No file associated with this node.</p>
                    )}
                </div>
            )}
        </LemonModal>
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

function RiskScoreWidgetForPR({ owner, name, number }: GitHogPullRequestRiskScoreLogicProps): JSX.Element {
    const logic = gitHogPullRequestRiskScoreLogic({ owner, name, number })
    const { riskScore, riskScoreLoading } = useValues(logic)
    const { refreshRiskScore } = useActions(logic)

    const styles = (riskScore && RISK_LEVEL_STYLES[riskScore.level]) || RISK_LEVEL_STYLES.moderate
    const factors = riskScore?.factors ?? []
    const headSha = riskScore?.head_sha ?? ''

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-2">
                <span className="font-semibold text-sm">Risk assessment</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={riskScoreLoading}
                    onClick={() => refreshRiskScore()}
                    tooltip="Force-recompute via LLM"
                >
                    Refresh
                </LemonButton>
            </div>
            <div className="px-4 py-4 flex flex-col gap-3">
                {riskScoreLoading && !riskScore ? (
                    <>
                        <LemonSkeleton className="h-6 w-24" />
                        <LemonSkeleton className="h-4 w-full" />
                        <LemonSkeleton className="h-4 w-3/4" />
                    </>
                ) : !riskScore ? (
                    <p className="text-secondary text-sm my-0">No assessment yet. Click Refresh to generate one.</p>
                ) : (
                    <>
                        <div>
                            <LemonTag type={styles.tag} size="small">
                                <span className={`font-semibold ${styles.text}`}>{styles.label}</span>
                            </LemonTag>
                        </div>
                        {riskScore.headline && (
                            <p className="text-sm text-primary my-0 leading-relaxed">{riskScore.headline}</p>
                        )}
                        {riskScore.truncated && (
                            <LemonTag type="warning" size="small">
                                Truncated — diff was too large for full context
                            </LemonTag>
                        )}
                        <div className="flex flex-col gap-2.5 mt-1">
                            {factors.map((f) => (
                                <div key={f.key} className="flex flex-col gap-1">
                                    <span className="text-xs font-medium">{f.label}</span>
                                    <FactorBar value={f.score} />
                                    <span className="text-xs text-muted leading-snug">{f.detail}</span>
                                </div>
                            ))}
                        </div>
                        <div className="text-xs text-muted">
                            {headSha ? `head ${headSha.slice(0, 7)} · ` : ''}
                            {riskScore.cached ? 'cached' : 'freshly computed'}
                        </div>
                    </>
                )}
            </div>
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
    const layoutProps: GitHogPRLayoutLogicProps = { owner, name, number }
    return (
        <BindLogic logic={gitHogPRReviewLogic} props={{ owner, name, number }}>
            <BindLogic logic={gitHogPRLayoutLogic} props={layoutProps}>
                <GitHogPRWorkspaceInner owner={owner} repoName={name} number={number} />
            </BindLogic>
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
    const { layoutItems } = useValues(gitHogPRLayoutLogic)
    const { setLayout, addWidget, removeWidget } = useActions(gitHogPRLayoutLogic)
    // `useContainerWidth` seeds `width` with 1280px (the hook's initialWidth
    // default) until the ResizeObserver has measured the real container. With
    // `measureBeforeMount: true` it keeps `mounted=false` until measurement
    // completes, which we use below to gate the grid render — otherwise the
    // first paint lays tiles out at 1280px wide and tiles past the viewport
    // edge stay off-screen.
    const {
        width: gridWidth,
        containerRef,
        mounted: gridMeasured,
    } = useContainerWidth({
        measureBeforeMount: true,
    })

    const widgets = useMemo(() => layoutItems.map((it) => it.i as WidgetType), [layoutItems])
    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))

    // react-grid-layout's `Layout` shape matches our persisted item shape 1:1.
    const handleLayoutChange = useCallback(
        (nextLayout: Layout[]) => {
            const items: GitHogLayoutItem[] = nextLayout.map((l) => ({
                i: l.i,
                x: l.x,
                y: l.y,
                w: l.w,
                h: l.h,
            }))
            // Only persist if anything actually changed — react-grid-layout emits
            // onLayoutChange on first mount too.
            const same =
                items.length === layoutItems.length &&
                items.every((it, idx) => {
                    const prev = layoutItems[idx]
                    return (
                        prev &&
                        prev.i === it.i &&
                        prev.x === it.x &&
                        prev.y === it.y &&
                        prev.w === it.w &&
                        prev.h === it.h
                    )
                })
            if (!same) {
                setLayout(items)
            }
        },
        [layoutItems, setLayout]
    )

    const pr = prDetail?.pull_request ?? null
    const renderWidget = (type: WidgetType): JSX.Element | null => {
        if (!prDetail || !pr) {
            return null
        }
        switch (type) {
            case 'conversation':
                return <ConversationWidget />
            case 'files':
                return <FilesWidget files={prDetail.files} />
            case 'agent':
                return <AgentWidget owner={owner} repo={repoName} pr={pr} files={prDetail.files} diff={prDetail.diff} />
            case 'dataFlow':
                return <DataFlowWidgetForPR owner={owner} name={repoName} number={number} files={prDetail.files} />
            case 'riskScore':
                return <RiskScoreWidgetForPR owner={owner} name={repoName} number={number} />
            case 'stats':
                return <StatsWidget pr={pr} />
            case 'reviewers':
                return <ReviewersWidget />
            default:
                return null
        }
    }

    const gridLayout: Layout[] = layoutItems.map((it) => {
        const def = WIDGET_DEFS[it.i as WidgetType]
        return {
            i: it.i,
            x: it.x,
            y: it.y,
            w: it.w,
            h: it.h,
            minW: 3,
            minH: 2,
            maxW: GRID_COLS,
            isDraggable: true,
            isResizable: true,
            ...(def ? { minH: Math.min(2, def.defaultH) } : {}),
        }
    })

    const isLoadingPRDetail = prDetailLoading && !prDetail
    const hasError = !isLoadingPRDetail && (!prDetail || !pr)

    // Loading, error, and content states all render inside the *same*
    // persistent root div that carries `containerRef`. `useContainerWidth`'s
    // internal `useEffect` only fires on first mount; if the ref-bearing
    // element swaps later (e.g. because we returned a spinner first), the
    // ResizeObserver stays bound to the discarded node and `mounted` never
    // flips — keeping the grid hidden. Keep this as one return with conditional
    // inner content.
    return (
        <div ref={containerRef as React.RefObject<HTMLDivElement>} className="flex flex-col gap-y-3 w-full min-w-0">
            {isLoadingPRDetail && (
                <div className="flex items-center justify-center py-16">
                    <Spinner className="text-2xl" />
                </div>
            )}
            {hasError && (
                <p className="text-secondary text-sm">
                    Could not load this pull request. Check that the team's GitHub integration has access to{' '}
                    <code>
                        {owner}/{repoName}
                    </code>
                    .
                </p>
            )}
            {pr && (
                <>
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
                        <div className="flex items-center gap-x-2 shrink-0">
                            <LemonButton type="secondary" size="small" icon={<IconGithub />} to={pr.url} targetBlank>
                                View on GitHub
                            </LemonButton>
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
                                    disabledReason={
                                        available.length === 0 ? 'All widgets are already visible' : undefined
                                    }
                                    size="small"
                                >
                                    Add widget
                                </LemonButton>
                            </LemonMenu>
                        </div>
                    </div>

                    {/* Compact risk summary pinned above the grid; the detailed `riskScore`
                        widget below stays available for the per-factor breakdown. */}
                    <RiskAssessmentBanner owner={owner} name={repoName} number={number} />

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
                        <div className="mt-2 w-full min-w-0 overflow-hidden">
                            {gridMeasured && gridWidth > 0 && (
                                <ReactGridLayout
                                    width={gridWidth}
                                    breakpoints={{ lg: 0 }}
                                    cols={{ lg: GRID_COLS }}
                                    layouts={{ lg: gridLayout }}
                                    rowHeight={GRID_ROW_HEIGHT}
                                    margin={GRID_MARGIN}
                                    containerPadding={GRID_PADDING}
                                    onLayoutChange={handleLayoutChange}
                                    dragConfig={{
                                        handle: '.githog-widget-drag-handle',
                                        cancel: 'a,button,input,textarea,.Popover',
                                    }}
                                    resizeConfig={{
                                        handles: ['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'] as const,
                                    }}
                                >
                                    {layoutItems.map((it) => {
                                        const type = it.i as WidgetType
                                        if (!WIDGET_DEFS[type]) {
                                            return null
                                        }
                                        return (
                                            <div key={it.i}>
                                                <WidgetShell
                                                    label={WIDGET_DEFS[type].label}
                                                    onRemove={() => removeWidget(type)}
                                                >
                                                    {renderWidget(type)}
                                                </WidgetShell>
                                            </div>
                                        )
                                    })}
                                </ReactGridLayout>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
