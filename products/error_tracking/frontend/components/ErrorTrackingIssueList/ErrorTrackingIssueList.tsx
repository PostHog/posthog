import { useActions } from 'kea'
import { useMemo } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { useSparklineData } from '../../hooks/use-sparkline-data'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION, sourceDisplay } from '../../utils'
import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../Assignee/AssigneeSelect'
import { StatusIndicator } from '../Indicators'
import { issueActionsLogic } from '../IssueActions/issueActionsLogic'
import { IssueStatusSelect } from '../IssueStatusSelect'
import { RuntimeIcon } from '../RuntimeIcon'
import { CustomSeparator } from '../TableColumns'
import { VolumeSparkline } from '../VolumeSparkline/VolumeSparkline'

/** Issue (flex) + volume sparkline + occurrences count. Fixed side columns so headers fit in dashboard tiles. */
export const ERROR_TRACKING_ISSUE_LIST_GRID_COLS = 'grid-cols-[minmax(0,1fr)_5.5rem_7rem]' as const

export function ErrorTrackingIssueListHeader(): JSX.Element {
    return (
        <div
            className={cn(
                'grid gap-3 border-b border-primary bg-bg-light px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted',
                ERROR_TRACKING_ISSUE_LIST_GRID_COLS
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
    orderBy = 'last_seen',
    canMutateIssues = true,
}: {
    issue: ErrorTrackingIssue
    orderBy?: string
    canMutateIssues?: boolean
}): JSX.Element {
    const { updateIssueAssignee, updateIssueStatus } = useActions(issueActionsLogic)
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

    return (
        <div
            className={cn(
                'grid items-start gap-3 border-b border-primary px-3 py-2 last:border-b-0 transition-colors hover:bg-fill-button-tertiary-hover',
                ERROR_TRACKING_ISSUE_LIST_GRID_COLS
            )}
        >
            <div className="flex min-w-0 flex-col gap-0.5">
                <Link
                    to={issueUrl}
                    className="flex items-center gap-2 text-sm text-primary"
                    onClick={() => prefetchIssueScene(issue)}
                >
                    <RuntimeIcon className="shrink-0" runtime={runtime} fontSize="0.75rem" />
                    <span className="line-clamp-1 font-semibold">{issue.name || 'Unknown Type'}</span>
                </Link>
                {issue.description ? (
                    <div title={issue.description} className="line-clamp-1 text-xs font-medium text-muted">
                        {issue.description}
                    </div>
                ) : null}
                {issue.function || issue.source ? (
                    <div className="line-clamp-1 text-xs font-light italic text-secondary">
                        {issue.function}
                        {issue.source ? <> in {sourceDisplay(issue.source)}</> : null}
                    </div>
                ) : null}
                <div className="flex items-center gap-1 text-secondary">
                    {canMutateIssues ? (
                        <IssueStatusSelect
                            status={issue.status}
                            onChange={(status) => updateIssueStatus(issue.id, status)}
                        />
                    ) : (
                        <StatusIndicator status={issue.status} size="small" />
                    )}
                    <CustomSeparator />
                    {canMutateIssues ? (
                        <AssigneeSelect
                            assignee={issue.assignee}
                            onChange={(assignee) => updateIssueAssignee(issue.id, assignee)}
                        >
                            {(anyAssignee) => (
                                <div
                                    className="ml-1 flex cursor-pointer items-center rounded p-[0.1rem] text-xs text-secondary hover:bg-fill-button-tertiary-hover"
                                    role="button"
                                >
                                    <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                                    <AssigneeLabelDisplay
                                        assignee={anyAssignee}
                                        className="ml-1 text-xs text-secondary"
                                        size="xsmall"
                                        placeholder="Unassigned"
                                    />
                                    <IconChevronDown />
                                </div>
                            )}
                        </AssigneeSelect>
                    ) : (
                        <AssigneeResolver assignee={issue.assignee}>
                            {({ assignee: resolvedAssignee }) => (
                                <div className="ml-1 flex items-center text-xs text-secondary">
                                    <AssigneeIconDisplay assignee={resolvedAssignee} size="xsmall" />
                                    <AssigneeLabelDisplay
                                        assignee={resolvedAssignee}
                                        className="ml-1 text-xs text-secondary"
                                        size="xsmall"
                                        placeholder="Unassigned"
                                    />
                                </div>
                            )}
                        </AssigneeResolver>
                    )}
                    <CustomSeparator />
                    {orderBy === 'first_seen' && issue.first_seen ? (
                        <>
                            <TZLabel
                                time={issue.first_seen}
                                className="ml-1 border-b border-dotted text-xs"
                                suffix="old"
                                delayMs={750}
                            />
                            <IconChevronRight className="mx-0.5 text-quaternary" fontSize="0.75rem" />
                        </>
                    ) : null}
                    {issue.last_seen ? (
                        <TZLabel time={issue.last_seen} className="ml-1 border-b border-dotted text-xs" delayMs={750} />
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
            <div className="pt-1 text-center text-base font-medium tabular-nums text-primary">
                {humanFriendlyLargeNumber(occurrences)}
            </div>
        </div>
    )
}

type ErrorTrackingIssueListProps = {
    issues: ErrorTrackingIssue[]
    orderBy?: string
    canMutateIssues?: boolean
    className?: string
    listClassName?: string
}

export function ErrorTrackingIssueList({
    issues,
    orderBy,
    canMutateIssues = true,
    className,
    listClassName,
}: ErrorTrackingIssueListProps): JSX.Element {
    return (
        <div className={cn('min-w-0 w-full max-w-full overflow-x-auto rounded border bg-surface-primary', className)}>
            <div className="w-full min-w-0">
                <ErrorTrackingIssueListHeader />
                <div className={listClassName} data-attr="error-tracking-issue-row">
                    {issues.map((issue) => (
                        <ErrorTrackingIssueListRow
                            key={issue.id}
                            issue={issue}
                            orderBy={orderBy}
                            canMutateIssues={canMutateIssues}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}
