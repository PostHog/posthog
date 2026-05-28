import { useMemo } from 'react'

import { Link } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { useSparklineData } from '../../hooks/use-sparkline-data'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION, sourceDisplay } from '../../utils'
import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { StatusIndicator } from '../Indicators'
import { RuntimeIcon } from '../RuntimeIcon'
import { CustomSeparator } from '../TableColumns'
import { VolumeSparkline } from '../VolumeSparkline/VolumeSparkline'

const GRID_COLS = 'grid-cols-[minmax(0,1fr)_clamp(5rem,18vw,7rem)_clamp(3.5rem,8vw,4.5rem)]'
const LIST_MIN_WIDTH_CLASS = 'min-w-[22rem]'

export function ErrorTrackingIssueListHeader(): JSX.Element {
    return (
        <div
            className={cn(
                'grid gap-3 border-b border-primary bg-bg-light px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-wide text-muted',
                GRID_COLS
            )}
        >
            <span>Issue</span>
            <span className="text-center">Volume</span>
            <span className="text-center">Occurrences</span>
        </div>
    )
}

function prefetchIssueScene(issue: ErrorTrackingIssue): void {
    const issueLogic = errorTrackingIssueSceneLogic({
        id: issue.id,
        timestamp: issue.last_seen,
    })
    issueLogic.mount()
    issueLogic.actions.setIssue(issue)
}

export function ErrorTrackingIssueListRow({
    issue,
    disableLink = false,
}: {
    issue: ErrorTrackingIssue
    disableLink?: boolean
}): JSX.Element {
    const runtime = getRuntimeFromLib(issue.library)
    const sparklineKey = issue.id ?? 'issue-unknown'
    const sparklineData = useSparklineData(issue.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    const occurrences = issue.aggregations?.occurrences ?? 0

    const issueUrl = useMemo(
        () =>
            urls.errorTrackingIssue(issue.id, {
                timestamp: issue.last_seen,
            }),
        [issue.id, issue.last_seen]
    )

    const rowClassName = cn(
        'grid items-start gap-3 border-b border-primary px-3 py-2 last:border-b-0',
        !disableLink && 'text-primary transition-colors hover:bg-fill-button-tertiary-hover',
        GRID_COLS
    )

    const rowContent = (
        <>
            <div className="flex min-w-0 flex-col gap-[2px] [--line-height:1.15rem]">
                <div className="flex h-(--line-height) items-center gap-2 text-[0.8rem]">
                    <RuntimeIcon className="shrink-0" runtime={runtime} fontSize="0.65rem" />
                    <span className="line-clamp-1 font-semibold">{issue.name || 'Unknown Type'}</span>
                </div>
                {issue.description ? (
                    <div
                        title={issue.description}
                        className="line-clamp-1 h-(--line-height) text-[0.7rem] font-medium text-[var(--gray-8)]"
                    >
                        {issue.description}
                    </div>
                ) : null}
                {issue.function || issue.source ? (
                    <div className="line-clamp-1 h-(--line-height) text-[0.65rem] font-light italic text-[var(--gray-6)]">
                        {issue.function}
                        {issue.source ? <> in {sourceDisplay(issue.source)}</> : null}
                    </div>
                ) : null}
                <div className="flex h-[calc(var(--line-height)*1.2)] items-center text-secondary">
                    <StatusIndicator
                        status={issue.status}
                        size="xsmall"
                        className="ml-0 text-[0.65rem] text-secondary"
                    />
                    <CustomSeparator />
                    <AssigneeResolver assignee={issue.assignee}>
                        {({ assignee }) => (
                            <div className="ml-1 flex items-center text-[0.65rem] text-secondary">
                                <AssigneeIconDisplay assignee={assignee} size="xsmall" />
                                <AssigneeLabelDisplay
                                    assignee={assignee}
                                    className="ml-1 text-[0.65rem] text-secondary"
                                    size="xsmall"
                                    placeholder="Unassigned"
                                />
                            </div>
                        )}
                    </AssigneeResolver>
                    <CustomSeparator />
                    {issue.last_seen ? (
                        <TZLabel
                            time={issue.last_seen}
                            className="ml-1 border-b border-dotted text-[0.65rem]"
                            delayMs={750}
                        />
                    ) : null}
                </div>
            </div>
            <div className="flex min-w-0 flex-col justify-center pt-1">
                <div className="h-8 min-h-8 w-full">
                    <VolumeSparkline
                        className="h-full"
                        data={sparklineData}
                        layout="compact"
                        xAxis="minimal"
                        sparklineKey={sparklineKey}
                    />
                </div>
            </div>
            <div className="pt-1 text-center text-base font-medium tabular-nums">
                {humanFriendlyLargeNumber(occurrences)}
            </div>
        </>
    )

    if (disableLink) {
        return <div className={rowClassName}>{rowContent}</div>
    }

    return (
        <Link to={issueUrl} className={rowClassName} onClick={() => prefetchIssueScene(issue)}>
            {rowContent}
        </Link>
    )
}

type ErrorTrackingIssueListProps = {
    issues: ErrorTrackingIssue[]
    className?: string
    listClassName?: string
    disableLinks?: boolean
}

export function ErrorTrackingIssueList({
    issues,
    className,
    listClassName,
    disableLinks = false,
}: ErrorTrackingIssueListProps): JSX.Element {
    return (
        <div className={cn('min-w-0 w-full max-w-full overflow-x-auto rounded border bg-surface-primary', className)}>
            <div className={LIST_MIN_WIDTH_CLASS}>
                <ErrorTrackingIssueListHeader />
                <div className={listClassName} data-attr="error-tracking-issue-row">
                    {issues.map((issue) => (
                        <ErrorTrackingIssueListRow key={issue.id} issue={issue} disableLink={disableLinks} />
                    ))}
                </div>
            </div>
        </div>
    )
}
