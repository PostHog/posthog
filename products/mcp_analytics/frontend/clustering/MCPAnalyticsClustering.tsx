import { useActions, useValues } from 'kea'

import { IconRefresh, IconSparkles } from '@posthog/icons'
import { Button, Skeleton, Spinner } from '@posthog/quill-primitives'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ClusterDetailPanel } from './ClusterDetailPanel'
import { ClusteringCoverageBanner } from './ClusteringCoverageBanner'
import { ClusteringSplitPane } from './ClusteringSplitPane'
import { ClusterListPanel } from './ClusterListPanel'
import { ClusterScorecards } from './ClusterScorecards'
import { ClusteringViewMode, mcpClusteringLogic } from './mcpClusteringLogic'
import { ToolDetailPanel } from './ToolDetailPanel'
import { ToolsListPanel } from './ToolsListPanel'

const VIEW_LABELS: Record<ClusteringViewMode, string> = {
    intents: 'By intent',
    tools: 'By tool',
}

function ViewToggle(): JSX.Element {
    const { viewMode } = useValues(mcpClusteringLogic)
    const { setViewMode } = useActions(mcpClusteringLogic)
    return (
        <div className="flex items-center gap-2">
            {(Object.keys(VIEW_LABELS) as ClusteringViewMode[]).map((key) => (
                <Button
                    key={key}
                    size="sm"
                    variant={viewMode === key ? 'default' : 'outline'}
                    onClick={() => setViewMode(key)}
                    data-attr={`mcp-analytics-clustering-view-${key}`}
                >
                    {VIEW_LABELS[key]}
                </Button>
            ))}
        </div>
    )
}

/**
 * Scopes both views to tools in the chosen categories. Hidden until a category is worth
 * showing: an always-visible empty dropdown would read as broken on a project that never
 * sets $mcp_tool_category. A selection carried in from the url counts, so a failed map
 * load still leaves the user a way to see and clear it.
 */
function CategoryScope(): JSX.Element | null {
    const { categoryScopeOptions, selectedCategories } = useValues(mcpClusteringLogic)
    const { setSelectedCategories } = useActions(mcpClusteringLogic)

    if (categoryScopeOptions.length === 0) {
        return null
    }

    return (
        <div className="w-full max-w-[420px] sm:w-[320px]">
            <TagsCombobox
                options={categoryScopeOptions}
                value={selectedCategories}
                onChange={setSelectedCategories}
                placeholder="All categories"
                allowCustomValues={false}
                dataAttr="mcp-clustering-category-scope"
            />
        </div>
    )
}

function StatusRow(): JSX.Element | null {
    const { snapshot, isComputing } = useValues(mcpClusteringLogic)
    const { recompute } = useActions(mcpClusteringLogic)

    if (snapshot.status === 'error') {
        return null
    }
    if (isComputing) {
        return (
            <div className="flex items-center gap-2 text-sm text-muted">
                <Spinner />
                Embedding intents and clustering — usually 30 to 60 seconds.
            </div>
        )
    }
    if (!snapshot.last_computed_at) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span>Last computed</span>
                <TZLabel time={snapshot.last_computed_at} />
                {/* Renders nothing when the snapshot predates coverage metadata, so it
                    carries its own separator rather than leaving a dangling one here. */}
                <ClusteringCoverageBanner />
            </div>
            <Button variant="outline" size="sm" onClick={recompute} data-attr="mcp-analytics-intent-clusters-recompute">
                <IconRefresh />
                Recompute
            </Button>
        </div>
    )
}

function EmptyState(): JSX.Element {
    const { recompute } = useActions(mcpClusteringLogic)
    const { snapshotLoading } = useValues(mcpClusteringLogic)
    return (
        <div
            className="bg-surface-primary border rounded p-8 flex flex-col items-center text-center gap-3 max-w-2xl mx-auto"
            data-quill
        >
            <IconSparkles className="text-4xl text-accent" />
            <h3 className="text-lg font-semibold">No intent clusters yet</h3>
            <p className="text-sm text-muted max-w-md">
                Clustering groups the goals your agents reported into themes, then shows which tools each theme routes
                to. It surfaces whether similar goals reach the same tools, and which routes fail most.
            </p>
            <Button variant="default" onClick={recompute} disabled={snapshotLoading}>
                {snapshotLoading ? <Spinner /> : <IconSparkles />}
                Compute intent clusters
            </Button>
            <span className="text-xs text-muted">
                Needs sessions whose calls carried an intent — usually a few minutes after they are recorded.
            </span>
        </div>
    )
}

function ComputingSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-24 w-full" />
                ))}
            </div>
            <Skeleton className="h-96 w-full" />
        </div>
    )
}

function ToolsViewEmptyState(): JSX.Element {
    const { recompute } = useActions(mcpClusteringLogic)
    const { snapshotLoading } = useValues(mcpClusteringLogic)
    return (
        <div className="bg-surface-primary border rounded p-8 flex flex-col items-center text-center gap-3 max-w-2xl mx-auto">
            <IconSparkles className="text-4xl text-accent" />
            <h3 className="text-lg font-semibold">No tool-level data in this snapshot</h3>
            <p className="text-sm text-muted max-w-md">
                This snapshot was computed before tool-level analytics existed. Recompute to see which intents each tool
                serves, how often agents discover it, and which tools compete for the same intents.
            </p>
            <Button variant="default" onClick={recompute} disabled={snapshotLoading}>
                {snapshotLoading ? <Spinner /> : <IconRefresh />}
                Recompute clusters
            </Button>
        </div>
    )
}

function ToolsView(): JSX.Element {
    const { hasToolPivot } = useValues(mcpClusteringLogic)

    if (!hasToolPivot) {
        return <ToolsViewEmptyState />
    }
    return (
        <ClusteringSplitPane
            logicKey="mcp-clustering-tools"
            // Wider than the intents list: the tool table carries seven columns. Still
            // leaves the detail enough room for its own intents table.
            defaultWidth={560}
            list={<ToolsListPanel />}
            detail={<ToolDetailPanel />}
        />
    )
}

function IntentsView(): JSX.Element {
    return (
        <>
            <ClusterScorecards />
            <ClusteringSplitPane
                logicKey="mcp-clustering-intents"
                defaultWidth={360}
                list={<ClusterListPanel />}
                detail={<ClusterDetailPanel />}
            />
        </>
    )
}

export function MCPAnalyticsClustering(): JSX.Element {
    const { snapshot, hasSnapshot, isComputing, snapshotLoading, viewMode } = useValues(mcpClusteringLogic)
    const { recompute } = useActions(mcpClusteringLogic)

    if (snapshot.status === 'error') {
        return (
            <div className="flex flex-col gap-3">
                <LemonBanner type="error" action={{ children: 'Retry', onClick: recompute }}>
                    {snapshot.error_message || 'The last clustering run failed.'}
                </LemonBanner>
            </div>
        )
    }

    if (isComputing || (snapshotLoading && !hasSnapshot)) {
        return (
            <div className="flex flex-col gap-4" data-quill>
                <StatusRow />
                <ComputingSkeleton />
            </div>
        )
    }

    if (!hasSnapshot) {
        return <EmptyState />
    }

    return (
        <div className="flex flex-col gap-4" data-quill>
            <StatusRow />
            <div className="flex flex-wrap items-center gap-3">
                <ViewToggle />
                <CategoryScope />
            </div>
            {viewMode === 'tools' ? <ToolsView /> : <IntentsView />}
        </div>
    )
}
