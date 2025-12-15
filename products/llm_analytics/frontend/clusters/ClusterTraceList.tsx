import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BulletList, parseBullets } from './ClusterDescriptionComponents'
import { Cluster, ClusterTraceInfo, TraceSummary } from './types'

interface ClusterTraceListProps {
    cluster: Cluster
    traceSummaries: Record<string, TraceSummary>
    loading: boolean
}

export function ClusterTraceList({ cluster, traceSummaries, loading }: ClusterTraceListProps): JSX.Element {
    const sortedTraces = Object.entries(cluster.traces)
        .sort(([, a], [, b]) => a.rank - b.rank)
        .slice(0, 20)

    if (loading && Object.keys(traceSummaries).length === 0) {
        return (
            <div className="p-4 flex items-center justify-center">
                <Spinner className="mr-2" />
                <span className="text-muted">Loading traces...</span>
            </div>
        )
    }

    return (
        <div className="divide-y">
            {sortedTraces.map(([traceId, traceInfo]) => (
                <TraceListItem
                    key={traceId}
                    traceId={traceId}
                    traceInfo={traceInfo}
                    summary={traceSummaries[traceId]}
                />
            ))}

            {Object.keys(cluster.traces).length > 20 && (
                <div className="p-3 text-center text-muted text-sm">
                    Showing top 20 of {Object.keys(cluster.traces).length} traces
                </div>
            )}
        </div>
    )
}

function TraceListItem({
    traceId,
    traceInfo,
    summary,
}: {
    traceId: string
    traceInfo: ClusterTraceInfo
    summary?: TraceSummary
}): JSX.Element {
    const [showFlow, setShowFlow] = useState(false)
    const [showBullets, setShowBullets] = useState(false)
    const [showNotes, setShowNotes] = useState(false)

    const bulletItems = summary?.bullets ? parseBullets(summary.bullets) : []
    const noteItems = summary?.interestingNotes ? parseBullets(summary.interestingNotes) : []

    return (
        <div className="p-3">
            {/* Header row with rank, title, and link */}
            <div className="flex items-center gap-2 mb-2">
                <LemonTag type="muted" size="small">
                    #{traceInfo.rank + 1}
                </LemonTag>
                <span className="font-medium text-sm flex-1 min-w-0 truncate">{summary?.title || 'Loading...'}</span>
                <Link
                    to={urls.llmAnalyticsTrace(traceId, traceInfo.timestamp ? { timestamp: traceInfo.timestamp } : {})}
                    className="text-xs text-link hover:underline shrink-0"
                >
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
                        <div className="p-2 bg-surface-secondary rounded text-xs font-mono whitespace-pre-wrap">
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
