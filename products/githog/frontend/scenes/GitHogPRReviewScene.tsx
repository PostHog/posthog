import { useState } from 'react'

import { IconCheck, IconCode, IconGitBranch, IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: GitHogPRReviewScene,
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

type WidgetType = 'conversation' | 'stats' | 'files' | 'reviewers'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; column: 'main' | 'side' }> = {
    conversation: { label: 'Conversation', description: 'Comments and review discussion', column: 'main' },
    files: { label: 'Files changed', description: 'Modified files with line counts', column: 'main' },
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

const WIDGET_COMPONENTS: Record<WidgetType, () => JSX.Element> = {
    conversation: ConversationWidget,
    stats: StatsWidget,
    reviewers: ReviewersWidget,
    files: FilesWidget,
}

// ─── Scene ───────────────────────────────────────────────────────────────────

export function GitHogPRReviewScene(): JSX.Element {
    const pr = SAMPLE_PR
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
                                        <Widget />
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
                                        <Widget />
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
