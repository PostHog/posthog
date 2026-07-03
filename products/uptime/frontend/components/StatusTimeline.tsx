import { Text, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'

import type { DailyBucketDTOApi } from '../generated/api.schemas'

function dailyStatusToBarClass(status: DailyBucketDTOApi['status']): string {
    switch (status) {
        case 'up':
            return 'bg-[var(--success-foreground)]'
        case 'degraded':
            return 'bg-[var(--warning-foreground)]'
        case 'down':
            return 'bg-[var(--destructive-foreground)]'
        default:
            return 'bg-border'
    }
}

function bucketTooltipText(bucket: DailyBucketDTOApi): string {
    const date = dayjs(bucket.date).format('MMM D, YYYY')
    if (bucket.status === 'no_data') {
        return `${date} — no checks`
    }
    if (bucket.status === 'up') {
        return `${date} — all ${bucket.total} checks succeeded`
    }
    if (bucket.status === 'down') {
        return `${date} — all ${bucket.total} checks failed`
    }
    return `${date} — ${bucket.failed} of ${bucket.total} checks failed`
}

export function StatusTimeline({ buckets }: { buckets: DailyBucketDTOApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <TooltipProvider>
                <div
                    className="flex h-6 items-center gap-px"
                    role="img"
                    aria-label={`Daily uptime status for the last ${buckets.length} days`}
                >
                    {buckets.map((bucket) => (
                        <Tooltip key={bucket.date}>
                            <TooltipTrigger
                                render={
                                    <div
                                        className={cn(
                                            'h-full flex-1 rounded-sm transition-opacity hover:opacity-80',
                                            dailyStatusToBarClass(bucket.status)
                                        )}
                                    />
                                }
                            />
                            <TooltipContent>{bucketTooltipText(bucket)}</TooltipContent>
                        </Tooltip>
                    ))}
                </div>
            </TooltipProvider>
            <div className="flex justify-between">
                <Text size="xxs" variant="muted" render={<span />}>
                    {buckets.length}d ago
                </Text>
                <Text size="xxs" variant="muted" render={<span />}>
                    Today
                </Text>
            </div>
        </div>
    )
}
