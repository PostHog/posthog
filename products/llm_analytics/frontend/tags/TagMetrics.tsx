import { useValues } from 'kea'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { llmTaggersLogic } from './llmTaggersLogic'
import { tagMetricsLogic } from './tagMetricsLogic'

export const TAG_METRICS_COLLECTION_ID = 'tag-metrics'

function SummaryCard({
    title,
    value,
    subtitle,
    colorClass,
}: {
    title: string
    value: string | number
    subtitle?: string
    colorClass?: string
}): JSX.Element {
    return (
        <div className="bg-bg-light border rounded p-4 flex flex-col">
            <div className="text-muted text-xs font-medium uppercase mb-2">{title}</div>
            <div className={`text-3xl font-semibold ${colorClass || ''}`}>{value}</div>
            {subtitle && <div className="text-muted text-sm mt-1">{subtitle}</div>}
        </div>
    )
}

function TopTagsCard({ tags }: { tags: { tag: string; count: number }[] }): JSX.Element {
    return (
        <div className="bg-bg-light border rounded p-4 flex flex-col col-span-2">
            <div className="text-muted text-xs font-medium uppercase mb-2">Top tags</div>
            {tags.length === 0 ? (
                <div className="text-muted text-sm">No tag data yet</div>
            ) : (
                <div className="flex flex-wrap gap-2 mt-1">
                    {tags.slice(0, 10).map((tagStat) => (
                        <LemonTag key={tagStat.tag} type="highlight" size="small">
                            {tagStat.tag} ({tagStat.count})
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function TagMetrics({ tabId }: { tabId?: string }): JSX.Element {
    const { summaryMetrics, tagStats, tagStatsLoading, enabledTaggerCount, chartQuery } = useValues(
        tagMetricsLogic({ tabId })
    )
    const { taggers } = useValues(llmTaggersLogic({ tabId }))

    if (tagStatsLoading) {
        return (
            <div className="space-y-4 mb-6">
                <LemonSkeleton className="h-96 w-full" />
            </div>
        )
    }

    return (
        <div className="mb-6">
            <div className="flex gap-4 h-96">
                {chartQuery ? (
                    <div className="flex-1 bg-bg-light rounded p-4 flex flex-col InsightCard h-full">
                        <h3 className="text-lg font-semibold mb-2">Tag frequency over time</h3>
                        <p className="text-muted text-sm mb-4">Showing how often each tag is applied</p>
                        <div className="flex-1 flex flex-col min-h-0">
                            <Query
                                query={{ kind: NodeKind.InsightVizNode, source: chartQuery } as InsightVizNode}
                                readOnly
                                embedded
                                inSharedMode
                                context={{
                                    insightProps: {
                                        dashboardItemId: 'new-tag-metrics-chart',
                                        dataNodeCollectionId: TAG_METRICS_COLLECTION_ID,
                                    },
                                }}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 bg-bg-light border rounded p-8 flex items-center justify-center">
                        <div className="text-muted text-center">
                            No tag data yet. Enable taggers and send some generations to see metrics.
                        </div>
                    </div>
                )}

                <div className="flex-1 grid grid-cols-2 gap-4">
                    <SummaryCard
                        title="Enabled taggers"
                        value={enabledTaggerCount}
                        subtitle={`${taggers.length} total`}
                    />
                    <SummaryCard
                        title="Tag runs"
                        value={summaryMetrics.total_runs}
                        subtitle={summaryMetrics.total_runs === 0 ? 'No activity' : undefined}
                    />
                    <TopTagsCard tags={tagStats} />
                </div>
            </div>
        </div>
    )
}
