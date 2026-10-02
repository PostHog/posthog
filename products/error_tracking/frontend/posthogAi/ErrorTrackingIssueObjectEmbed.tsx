import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { compactNumber } from 'lib/utils/numbers'

import type { ObjectEmbedProps } from 'products/posthog_ai/frontend/api/types'

import { type IssueStatus, StatusIndicator } from '../components/Indicators'
import { DEFAULT_DATE_RANGE } from '../components/IssueFilters/issueFiltersLogic'
import { VolumeSparkline } from '../components/VolumeSparkline/VolumeSparkline'
import { useSparklineData } from '../hooks/use-sparkline-data'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from '../utils'
import { errorTrackingIssueObjectEmbedLogic } from './errorTrackingIssueObjectEmbedLogic'

function IssueVolume({ id }: { id: string }): JSX.Element {
    const { summary, summaryLoading } = useValues(errorTrackingIssueObjectEmbedLogic({ id }))
    const data = useSparklineData(
        summary?.aggregations ?? undefined,
        ERROR_TRACKING_DETAILS_RESOLUTION,
        DEFAULT_DATE_RANGE
    )
    if (!summary && summaryLoading) {
        return <LemonSkeleton className="h-24" />
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs text-secondary">Occurrences</span>
            <div className="h-24 w-full">
                <VolumeSparkline
                    className="h-full"
                    data={data}
                    layout="compact"
                    xAxis="minimal"
                    sparklineKey={`task-artifact-issue-${id}`}
                />
            </div>
        </div>
    )
}

/** A read-only error tracking issue summary: title, status, counts and the occurrence volume. */
export function ErrorTrackingIssueObjectEmbed({ objectId }: ObjectEmbedProps): JSX.Element {
    const { issue, issueMissing, summary } = useValues(errorTrackingIssueObjectEmbedLogic({ id: objectId }))
    if (issueMissing) {
        return <NotFound object="issue" />
    }
    if (!issue) {
        return (
            <div className="flex flex-col gap-2 p-4">
                <LemonSkeleton className="h-6 w-48" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }
    const aggregations = summary?.aggregations
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{issue.name || 'Unnamed issue'}</span>
                    {/* The generated type widens the status to a string. An unknown value renders as "Unknown". */}
                    <StatusIndicator status={issue.status as IssueStatus} size="xsmall" withTooltip />
                </div>
                {issue.description ? (
                    <p className="m-0 line-clamp-3 font-mono text-xs text-secondary">{issue.description}</p>
                ) : null}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-secondary">
                    {aggregations ? (
                        <>
                            <span>{compactNumber(aggregations.occurrences)} occurrences</span>
                            <span>{compactNumber(aggregations.users)} users</span>
                            <span>{compactNumber(aggregations.sessions)} sessions</span>
                        </>
                    ) : null}
                    {issue.first_seen ? (
                        <span>
                            First seen <TZLabel time={issue.first_seen} />
                        </span>
                    ) : null}
                    {summary?.lastSeen ? (
                        <span>
                            Last seen <TZLabel time={summary.lastSeen} />
                        </span>
                    ) : null}
                </div>
            </div>
            <div className="rounded-md border border-primary bg-surface-primary p-2">
                <IssueVolume id={objectId} />
            </div>
        </div>
    )
}
