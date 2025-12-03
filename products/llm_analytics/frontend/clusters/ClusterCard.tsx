import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ClusterTraceList } from './ClusterTraceList'
import { Cluster, TraceSummary } from './types'

interface ClusterCardProps {
    cluster: Cluster
    totalTraces: number
    isExpanded: boolean
    onToggleExpand: () => void
    traceSummaries: Record<string, TraceSummary>
    loadingTraces: boolean
}

export function ClusterCard({
    cluster,
    totalTraces,
    isExpanded,
    onToggleExpand,
    traceSummaries,
    loadingTraces,
}: ClusterCardProps): JSX.Element {
    const percentage = totalTraces > 0 ? Math.round((cluster.size / totalTraces) * 100) : 0
    return (
        <div className="border rounded-lg bg-surface-primary overflow-hidden transition-all">
            {/* Card Header */}
            <div className="p-4 cursor-pointer hover:bg-surface-secondary transition-colors" onClick={onToggleExpand}>
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2 mb-2">
                            <h3 className="font-semibold text-base truncate">{cluster.title}</h3>
                            <LemonTag type="muted">
                                {cluster.size} traces ({percentage}%)
                            </LemonTag>
                        </div>
                        <p className="text-secondary text-sm">{cluster.description}</p>
                    </div>
                    <LemonButton
                        size="small"
                        noPadding
                        icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onToggleExpand()
                        }}
                    />
                </div>
            </div>

            {/* Expanded Trace List */}
            {isExpanded && (
                <div className="border-t">
                    <ClusterTraceList cluster={cluster} traceSummaries={traceSummaries} loading={loadingTraces} />
                </div>
            )}
        </div>
    )
}
