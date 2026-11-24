import { useActions, useValues } from 'kea'

import { Empty, EmptyDescription, EmptyHeader, Skeleton, Text } from '@posthog/quill'

import { issueRateLimitConfigLogic } from './issueRateLimitConfigLogic'
import { QuillRateLimitChartToolbar } from './QuillRateLimitChartToolbar'
import { RateLimitHistoryChart } from './RateLimitHistoryChart'
import { RateLimitSimulationChart } from './RateLimitSimulationChart'

export function QuillIssueRateLimitPreview(): JSX.Element {
    const {
        selectedIssue,
        selectedIssueVolume,
        selectedIssueVolumeLoading,
        selectedIssueHistory,
        selectedIssueHistoryLoading,
        chartMode,
        configForm,
        topIssues,
    } = useValues(issueRateLimitConfigLogic)
    const { setChartMode, refreshChart } = useActions(issueRateLimitConfigLogic)

    const limit = configForm.per_issue_rate_limit_value
    const bucketMinutes = configForm.per_issue_rate_limit_bucket_size_minutes
    const chartLoading = chartMode === 'history' ? selectedIssueHistoryLoading : selectedIssueVolumeLoading

    const heading = (
        <Text size="sm" weight="medium" className="truncate" render={<p className="m-0" />}>
            {selectedIssue ? `"${selectedIssue.name || 'Untitled issue'}"` : 'Volume'}
        </Text>
    )

    if (topIssues.length === 0) {
        return (
            <div className="flex flex-col gap-1">
                {heading}
                <Empty className="h-80 rounded-md border border-border">
                    <EmptyHeader>
                        <EmptyDescription>Pick an issue from the list to preview its volume.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {heading}
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {chartMode === 'simulation'
                    ? "This shows the issue's past traffic to help you choose a rate limit."
                    : "This shows how many of the issue's exceptions were recorded vs dropped based on your rate limits."}
            </Text>
            <QuillRateLimitChartToolbar
                chartMode={chartMode}
                onChartModeChange={setChartMode}
                bucketMinutes={bucketMinutes}
                loading={chartLoading}
                onRefresh={refreshChart}
            />
            {chartMode === 'simulation' ? (
                selectedIssueVolumeLoading && selectedIssueVolume.length === 0 ? (
                    <Skeleton className="w-full h-80" />
                ) : (
                    <RateLimitSimulationChart
                        volume={selectedIssueVolume}
                        rateLimit={limit}
                        bucketMinutes={bucketMinutes}
                    />
                )
            ) : selectedIssueHistoryLoading && selectedIssueHistory.length === 0 ? (
                <Skeleton className="w-full h-80" />
            ) : (
                <RateLimitHistoryChart
                    history={selectedIssueHistory}
                    bucketMinutes={bucketMinutes}
                    emptyMessage="No rate limiting activity recorded yet for this issue. Exceptions dropped by your per-issue limit will appear here."
                />
            )}
        </div>
    )
}
