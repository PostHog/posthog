import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { BulletList, parseBullets } from './ClusterDescriptionComponents'
import { formatEvalTitle } from './traceSummaryLoader'
import { Cluster, ClusterItemInfo, ClusteringLevel, TraceSummary } from './types'

interface ClusterTraceListProps {
    cluster: Cluster
    traceSummaries: Record<string, TraceSummary>
    loading: boolean
    clusteringLevel?: ClusteringLevel
}

export function ClusterTraceList({
    cluster,
    traceSummaries,
    loading,
    clusteringLevel = 'trace',
}: ClusterTraceListProps): JSX.Element {
    const sortedTraces = Object.entries(cluster.traces)
        .sort(([, a], [, b]) => a.rank - b.rank)
        .slice(0, 20)

    const itemLabel =
        clusteringLevel === 'generation' ? 'generations' : clusteringLevel === 'evaluation' ? 'evaluations' : 'traces'

    if (loading && Object.keys(traceSummaries).length === 0) {
        return (
            <div className="p-4 flex items-center justify-center">
                <Spinner className="mr-2" />
                <span className="text-muted">Loading {itemLabel}...</span>
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
                    clusteringLevel={clusteringLevel}
                />
            ))}

            {Object.keys(cluster.traces).length > 20 && (
                <div className="p-3 text-center text-muted text-sm">
                    Showing top 20 of {Object.keys(cluster.traces).length} {itemLabel}
                </div>
            )}
        </div>
    )
}

function TraceListItem({
    traceId,
    traceInfo,
    summary,
    clusteringLevel = 'trace',
}: {
    traceId: string
    traceInfo: ClusterItemInfo
    summary?: TraceSummary
    clusteringLevel?: ClusteringLevel
}): JSX.Element {
    const [showFlow, setShowFlow] = useState(false)
    const [showBullets, setShowBullets] = useState(false)
    const [showNotes, setShowNotes] = useState(false)

    const bulletItems = summary?.bullets ? parseBullets(summary.bullets) : []
    const noteItems = summary?.interestingNotes ? parseBullets(summary.interestingNotes) : []
    const isEvalLevel = clusteringLevel === 'evaluation'

    // For eval members, the cluster item id is the $ai_evaluation event uuid.
    // Its "trace" context is whatever the evaluator was judging — we jump to the
    // parent trace with the linked generation uuid highlighted, so the user
    // lands directly on the generation the evaluator reacted to.
    //
    // Only use summary.traceId — the backend falls back to `trace_id = eval_uuid`
    // for cluster items whose metadata join couldn't resolve (events older than
    // METADATA_LOOKBACK), and routing to `/traces/<eval_uuid>` 404s. Hiding the
    // link when summary hasn't loaded is the right signal.
    const evalLinkedTraceId = summary?.traceId
    const evalLinkedGenerationId = summary?.generationId

    const linkHref = isEvalLevel
        ? evalLinkedTraceId
            ? urls.llmAnalyticsTrace(evalLinkedTraceId, {
                  tab: 'summary',
                  ...(evalLinkedGenerationId ? { event: evalLinkedGenerationId } : {}),
                  ...(traceInfo.timestamp ? { timestamp: dayjs.utc(traceInfo.timestamp).toISOString() } : {}),
              })
            : null
        : urls.llmAnalyticsTrace(
              clusteringLevel === 'generation' ? traceInfo.trace_id : traceId,
              clusteringLevel === 'generation'
                  ? {
                        tab: 'summary',
                        event: traceInfo.generation_id,
                        ...(traceInfo.timestamp ? { timestamp: dayjs.utc(traceInfo.timestamp).toISOString() } : {}),
                    }
                  : {
                        tab: 'summary',
                        ...(traceInfo.timestamp ? { timestamp: dayjs.utc(traceInfo.timestamp).toISOString() } : {}),
                    }
          )

    const linkLabel = clusteringLevel === 'trace' ? 'View trace →' : 'View generation →'

    const verdictTagType: 'success' | 'danger' | 'warning' | 'muted' =
        summary?.evaluationVerdict === 'pass'
            ? 'success'
            : summary?.evaluationVerdict === 'fail'
              ? 'danger'
              : summary?.evaluationVerdict === 'n/a'
                ? 'warning'
                : 'muted'

    return (
        <div className="p-3">
            {/* Header row with rank, title, and link */}
            <div className="flex items-center gap-2 mb-2">
                <LemonTag type="muted" size="small">
                    #{traceInfo.rank + 1}
                </LemonTag>
                {isEvalLevel && summary?.evaluationVerdict && (
                    <LemonTag type={verdictTagType} size="small">
                        {summary.evaluationVerdict}
                    </LemonTag>
                )}
                <span className="font-medium text-sm flex-1 min-w-0 truncate">
                    {isEvalLevel ? formatEvalTitle(summary, 100) || 'Loading...' : summary?.title || 'Loading...'}
                </span>
                {linkHref && (
                    <Link
                        to={linkHref}
                        className="text-xs text-link hover:underline shrink-0"
                        data-attr="clusters-view-trace-link"
                    >
                        {linkLabel}
                    </Link>
                )}
            </div>

            {summary ? (
                <div className="space-y-2">
                    {/* For eval items, render short reasoning inline — most evaluator reasoning is
                        a sentence or two, and a separate toggle adds friction. Long reasoning still
                        gets the collapsible "Reasoning" button below. */}
                    {isEvalLevel && summary.evaluationReasoning && summary.evaluationReasoning.length <= 220 && (
                        <div className="text-xs text-muted whitespace-pre-wrap">{summary.evaluationReasoning}</div>
                    )}
                    {/* Expandable buttons row */}
                    <div className="flex items-center gap-2">
                        {summary.flowDiagram && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showFlow ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowFlow(!showFlow)}
                                data-attr="clusters-trace-flow-toggle"
                            >
                                Flow
                            </LemonButton>
                        )}
                        {/* Hide the "Reasoning" toggle when we rendered short reasoning inline above. */}
                        {bulletItems.length > 0 &&
                            !(
                                isEvalLevel &&
                                summary.evaluationReasoning &&
                                summary.evaluationReasoning.length <= 220
                            ) && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={showBullets ? <IconChevronDown /> : <IconChevronRight />}
                                    onClick={() => setShowBullets(!showBullets)}
                                    data-attr="clusters-trace-summary-toggle"
                                >
                                    {isEvalLevel ? 'Reasoning' : 'Summary'}
                                </LemonButton>
                            )}
                        {noteItems.length > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={showNotes ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowNotes(!showNotes)}
                                data-attr="clusters-trace-notes-toggle"
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
