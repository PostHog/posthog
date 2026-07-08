import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingIssueListHeader, ERROR_TRACKING_ISSUE_LIST_GRID_COLS } from './ErrorTrackingIssueList'

function ErrorTrackingIssueListSkeletonRow(): JSX.Element {
    return (
        <div
            className={cn(
                'grid items-start gap-3 border-b border-primary px-3 py-2 last:border-b-0',
                ERROR_TRACKING_ISSUE_LIST_GRID_COLS
            )}
            aria-hidden
        >
            <div className="flex min-w-0 flex-col gap-1.5">
                <div className="flex items-center gap-2">
                    <LemonSkeleton className="h-3.5 w-3.5 shrink-0 rounded-sm" />
                    <LemonSkeleton className="h-3.5 w-[72%] max-w-md" />
                </div>
                <LemonSkeleton className="h-3 w-[88%] max-w-lg" />
                <LemonSkeleton className="h-2.5 w-[55%] max-w-xs" />
                <div className="flex items-center gap-2 pt-0.5">
                    <LemonSkeleton className="h-3 w-14" />
                    <LemonSkeleton className="h-3 w-20" />
                    <LemonSkeleton className="h-3 w-16" />
                </div>
            </div>
            <div className="flex min-w-0 flex-col justify-center pt-1">
                <LemonSkeleton className="h-8 w-full" />
            </div>
            <div className="flex justify-center pt-1">
                <LemonSkeleton className="h-5 w-10" />
            </div>
        </div>
    )
}

type ErrorTrackingIssueListSkeletonProps = {
    rowCount?: number
    className?: string
}

export function ErrorTrackingIssueListSkeleton({
    rowCount = 5,
    className,
}: ErrorTrackingIssueListSkeletonProps): JSX.Element {
    return (
        <div
            className={cn('min-w-0 w-full max-w-full overflow-x-auto rounded border bg-surface-primary', className)}
            aria-busy
            aria-label="Loading issues"
        >
            <div className="w-full min-w-0">
                <ErrorTrackingIssueListHeader />
                <div>
                    {Array.from({ length: rowCount }, (_, index) => (
                        <ErrorTrackingIssueListSkeletonRow key={index} />
                    ))}
                </div>
            </div>
        </div>
    )
}
