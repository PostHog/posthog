import { useActions, useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { Button, Empty, EmptyDescription, EmptyHeader, Skeleton, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { issueRateLimitConfigLogic } from './issueRateLimitConfigLogic'
import { formatTotalDuration } from './RateLimitSimulationChart'

export function QuillIssueRateLimitList(): JSX.Element {
    const { topIssues, topIssuesLoading, selectedIssueId, configForm } = useValues(issueRateLimitConfigLogic)
    const { selectIssue } = useActions(issueRateLimitConfigLogic)

    const windowLabel = formatTotalDuration(configForm.per_issue_rate_limit_bucket_size_minutes)

    return (
        <div className="flex flex-col gap-1">
            <Text size="sm" weight="medium" render={<p className="m-0" />}>
                <span>Most active issues - past </span>
                <span translate="no">{windowLabel}</span>
            </Text>
            {topIssuesLoading ? (
                <Skeleton className="w-full h-80" />
            ) : topIssues.length === 0 ? (
                <Empty className="h-80 rounded-md border border-border">
                    <EmptyHeader>
                        <EmptyDescription>
                            <span>No exceptions captured in the past </span>
                            <span translate="no">{windowLabel}</span>
                            <span> yet.</span>
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <div className="h-80 divide-y divide-border overflow-y-auto rounded-md border border-border scroll-mask-y-4 scroll-py-4">
                    {topIssues.map((issue) => {
                        const isSelected = issue.issue_id === selectedIssueId
                        const issueName = issue.name || 'Untitled issue'

                        return (
                            <div
                                key={issue.issue_id}
                                className={cn('flex items-center gap-1 pr-2', isSelected && 'bg-fill-selected')}
                            >
                                <button
                                    type="button"
                                    aria-pressed={isSelected}
                                    className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 py-2 pl-3 text-left hover:bg-fill-hover"
                                    onClick={() => selectIssue(issue.issue_id)}
                                    data-attr="issue-rate-limit-row"
                                >
                                    <span className="flex min-w-0 flex-1 flex-col">
                                        <span className="truncate text-sm font-medium">{issueName}</span>
                                        {issue.description ? (
                                            <span className="truncate text-xs text-muted-foreground">
                                                {issue.description}
                                            </span>
                                        ) : null}
                                    </span>
                                    <span className="flex shrink-0 flex-col text-right">
                                        <span className="text-sm font-medium" translate="no">
                                            {humanFriendlyLargeNumber(issue.occurrences)}
                                        </span>
                                        <span className="text-xs text-muted-foreground">events</span>
                                    </span>
                                </button>
                                <Button
                                    size="icon-sm"
                                    aria-label={`Open ${issueName}`}
                                    tooltip="Open issue"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.errorTrackingIssue(issue.issue_id)} />}
                                >
                                    <IconArrowUpRight />
                                </Button>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
