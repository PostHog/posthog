import { Button, Skeleton, Text } from '@posthog/quill'

import { LogsFilterPreviewLookback, LogsFilterPreviewMetric, TOP_SERVICES_LIMIT } from './logsFilterVolumePreview'

export interface QuillLogsFilterVolumeSparklineProps {
    lookback: LogsFilterPreviewLookback
    metric: LogsFilterPreviewMetric
    hasFilters: boolean
    loading: boolean
    failed: boolean
    empty: boolean
    formattedTotal: string
    chart: JSX.Element
    caption: JSX.Element | null | undefined
    onRetry: () => void
}

export function QuillLogsFilterVolumeSparkline({
    lookback,
    metric,
    hasFilters,
    loading,
    failed,
    empty,
    formattedTotal,
    chart,
    caption,
    onRetry,
}: QuillLogsFilterVolumeSparklineProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center justify-between gap-x-2">
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Volume preview by service (last {lookback}, top {TOP_SERVICES_LIMIT}
                    {metric === 'bytes' ? ', bytes' : ''})
                </Text>
                {hasFilters && !loading ? (
                    <Text size="xs" variant="muted" render={<span className="m-0" translate="no" />}>
                        {formattedTotal}
                    </Text>
                ) : null}
            </div>
            {/* Quill charts fill a *flex* parent (their root is flex-1), so the sized box is a flex column. */}
            <div className="relative flex h-32 flex-col rounded-md border border-border bg-background px-2 py-1">
                {!hasFilters ? (
                    <div className="flex h-full items-center justify-center">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            Add a filter above to preview matching log volume
                        </Text>
                    </div>
                ) : loading ? (
                    <Skeleton className="h-full w-full" />
                ) : failed ? (
                    <div className="flex h-full flex-col items-center justify-center gap-1">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            Couldn't load the volume preview.
                        </Text>
                        <Button variant="outline" onClick={onRetry}>
                            Retry
                        </Button>
                    </div>
                ) : empty ? (
                    <div className="flex h-full items-center justify-center">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            No logs match these filters in the last {lookback}
                        </Text>
                    </div>
                ) : (
                    chart
                )}
            </div>
            {caption}
        </div>
    )
}
