import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ClusterDetailLogicProps, clusterDetailLogic } from './clusterDetailLogic'
import { ClusterTraceInfo, TraceSummary } from './types'

interface BulletItem {
    text: string
    line_refs: string
}

function parseBullets(bullets: string): BulletItem[] {
    try {
        const parsed = JSON.parse(bullets)
        if (Array.isArray(parsed)) {
            return parsed as BulletItem[]
        }
        return []
    } catch {
        return bullets ? [{ text: bullets, line_refs: '' }] : []
    }
}

export const scene: SceneExport<ClusterDetailLogicProps> = {
    component: LLMAnalyticsClusterScene,
    logic: clusterDetailLogic,
    paramsToProps: ({ params: { runId, clusterId } }) => ({
        runId: runId ? decodeURIComponent(runId) : '',
        clusterId: clusterId ? parseInt(clusterId, 10) : 0,
    }),
}

export function LLMAnalyticsClusterScene(): JSX.Element {
    const {
        cluster,
        clusterDataLoading,
        isOutlierCluster,
        totalTraces,
        totalPages,
        currentPage,
        paginatedTracesWithSummaries,
        traceSummariesLoading,
        windowStart,
        windowEnd,
    } = useValues(clusterDetailLogic)
    const { setPage } = useActions(clusterDetailLogic)

    if (clusterDataLoading) {
        return (
            <SceneContent>
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-8 w-1/3" />
                    <LemonSkeleton className="h-4 w-2/3" />
                    <div className="flex gap-2">
                        <LemonSkeleton className="h-6 w-24" />
                        <LemonSkeleton className="h-6 w-24" />
                    </div>
                    <div className="space-y-3 mt-4">
                        {[...Array(5)].map((_, i) => (
                            <LemonSkeleton key={i} className="h-20 w-full" />
                        ))}
                    </div>
                </div>
            </SceneContent>
        )
    }

    if (!cluster) {
        return <NotFound object="cluster" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={cluster.title}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <Link to={urls.llmAnalyticsClusters()}>
                        <LemonButton type="secondary" size="small">
                            Back to clusters
                        </LemonButton>
                    </Link>
                }
            />

            {/* Cluster info header */}
            <div
                className={`border rounded-lg p-4 mb-4 ${
                    isOutlierCluster ? 'bg-surface-primary border-dashed border-warning-dark' : 'bg-surface-primary'
                }`}
            >
                <div className="flex flex-wrap items-center gap-3 mb-2">
                    <LemonTag type={isOutlierCluster ? 'caution' : 'primary'} size="medium">
                        {totalTraces} traces
                    </LemonTag>
                    {windowStart && windowEnd && (
                        <span className="text-muted text-sm">
                            Window: {new Date(windowStart).toLocaleDateString()} -{' '}
                            {new Date(windowEnd).toLocaleDateString()}
                        </span>
                    )}
                </div>
                <p className="text-secondary m-0">{cluster.description}</p>
            </div>

            {/* Pagination controls at top */}
            {totalPages > 1 && (
                <div className="flex justify-between items-center mb-4">
                    <span className="text-muted text-sm">
                        Showing {(currentPage - 1) * 50 + 1}-{Math.min(currentPage * 50, totalTraces)} of {totalTraces}{' '}
                        traces
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronLeft />}
                            disabled={currentPage === 1}
                            onClick={() => setPage(currentPage - 1)}
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronRight />}
                            disabled={currentPage === totalPages}
                            onClick={() => setPage(currentPage + 1)}
                        />
                    </div>
                </div>
            )}

            {/* Trace list */}
            <div className="border rounded-lg overflow-hidden divide-y">
                {traceSummariesLoading && paginatedTracesWithSummaries.length === 0 ? (
                    <div className="p-4 flex items-center justify-center">
                        <Spinner className="mr-2" />
                        <span className="text-muted">Loading traces...</span>
                    </div>
                ) : (
                    paginatedTracesWithSummaries.map(
                        ({
                            traceId,
                            traceInfo,
                            summary,
                        }: {
                            traceId: string
                            traceInfo: ClusterTraceInfo
                            summary?: TraceSummary
                        }) => (
                            <TraceListItem
                                key={traceId}
                                traceId={traceId}
                                traceInfo={traceInfo}
                                summary={summary}
                                page={currentPage}
                            />
                        )
                    )
                )}
            </div>

            {/* Pagination controls at bottom */}
            {totalPages > 1 && (
                <div className="flex justify-center mt-4">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronLeft />}
                            disabled={currentPage === 1}
                            onClick={() => setPage(currentPage - 1)}
                        />
                        <span className="text-sm">
                            Page {currentPage} of {totalPages}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronRight />}
                            disabled={currentPage === totalPages}
                            onClick={() => setPage(currentPage + 1)}
                        />
                    </div>
                </div>
            )}
        </SceneContent>
    )
}

function TraceListItem({
    traceId,
    traceInfo,
    summary,
    page,
}: {
    traceId: string
    traceInfo: ClusterTraceInfo
    summary?: TraceSummary
    page: number
}): JSX.Element {
    const [showFlow, setShowFlow] = useState(false)
    const [showBullets, setShowBullets] = useState(false)
    const [showNotes, setShowNotes] = useState(false)

    const bulletItems = summary?.bullets ? parseBullets(summary.bullets) : []
    const noteItems = summary?.interestingNotes ? parseBullets(summary.interestingNotes) : []

    // Calculate display rank based on page (rank is 0-indexed in data)
    const displayRank = (page - 1) * 50 + traceInfo.rank + 1

    return (
        <div className="p-4 hover:bg-surface-secondary transition-colors">
            {/* Header row with rank, title, and link */}
            <div className="flex items-center gap-2 mb-2">
                <LemonTag type="muted" size="small">
                    #{displayRank}
                </LemonTag>
                <span className="font-medium flex-1 min-w-0 truncate">{summary?.title || 'Loading...'}</span>
                <Link to={urls.llmAnalyticsTrace(traceId)} className="text-sm text-link hover:underline shrink-0">
                    View trace →
                </Link>
            </div>

            {summary ? (
                <div className="space-y-2">
                    {/* Expandable buttons row */}
                    <div className="flex items-center gap-2">
                        {summary.flowDiagram && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showFlow ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowFlow(!showFlow)}
                            >
                                Flow
                            </LemonButton>
                        )}
                        {bulletItems.length > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showBullets ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowBullets(!showBullets)}
                            >
                                Summary
                            </LemonButton>
                        )}
                        {noteItems.length > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showNotes ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowNotes(!showNotes)}
                            >
                                Notes
                            </LemonButton>
                        )}
                    </div>

                    {/* Expanded content */}
                    {showFlow && summary.flowDiagram && (
                        <div className="p-3 bg-surface-tertiary rounded text-sm font-mono whitespace-pre-wrap">
                            {summary.flowDiagram}
                        </div>
                    )}

                    {showBullets && bulletItems.length > 0 && <BulletList items={bulletItems} />}

                    {showNotes && noteItems.length > 0 && <BulletList items={noteItems} />}
                </div>
            ) : (
                <div className="text-muted text-sm">Loading summary...</div>
            )}
        </div>
    )
}

function BulletList({ items }: { items: BulletItem[] }): JSX.Element {
    return (
        <ul className="p-3 bg-surface-tertiary rounded text-sm space-y-1 list-disc list-inside">
            {items.map((item, index) => (
                <li key={index}>{item.text}</li>
            ))}
        </ul>
    )
}

export default LLMAnalyticsClusterScene
