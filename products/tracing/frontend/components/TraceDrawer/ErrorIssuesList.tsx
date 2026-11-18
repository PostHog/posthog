import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { pluralize } from 'lib/utils/strings'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { ErrorTrackingIssueCard } from 'products/error_tracking/frontend/ErrorTrackingIssueCard'

export interface ErrorIssuesListProps {
    issues: MaxErrorTrackingIssuePreview[]
    loading: boolean
    failed: boolean
    onRetry: () => void
    failedMessage: string
    emptyTitle: string
    emptyDescription: string
    /** Ends the summary line, for example "in this span". */
    where: string
}

export function ErrorIssuesList({
    issues,
    loading,
    failed,
    onRetry,
    failedMessage,
    emptyTitle,
    emptyDescription,
    where,
}: ErrorIssuesListProps): JSX.Element {
    if (loading) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-16 w-full" repeat={3} />
            </div>
        )
    }

    if (failed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: onRetry }}>
                {failedMessage}
            </LemonBanner>
        )
    }

    if (issues.length === 0) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage title={emptyTitle} description={emptyDescription} size="small" />
            </div>
        )
    }

    const totalOccurrences = issues.reduce((sum, issue) => sum + issue.occurrences, 0)
    return (
        <div className="flex flex-col">
            <p className="text-muted text-sm mb-2">
                {pluralize(issues.length, 'issue')} with {pluralize(totalOccurrences, 'occurrence')} {where}
            </p>
            {issues.map((issue) => (
                <ErrorTrackingIssueCard key={issue.id} issue={issue} showUserCount={false} />
            ))}
        </div>
    )
}
