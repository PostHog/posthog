import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ErrorTrackingIssueCard } from 'scenes/max/messages/ErrorTrackingIssueCard'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { RelatedErrorsLogicProps, relatedErrorsLogic } from './relatedErrorsLogic'

export interface RelatedErrorsTabProps {
    logUuid: string
    logTimestamp: string
    sessionId: string | null
}

export function RelatedErrorsTab({ logUuid, logTimestamp, sessionId }: RelatedErrorsTabProps): JSX.Element {
    if (!sessionId) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage
                    title="No session ID found"
                    description="To see related errors, link your logs to session replay by including a session ID."
                    buttonText="Learn more"
                    buttonTo="https://posthog.com/docs/logs/link-session-replay"
                    size="small"
                />
            </div>
        )
    }

    const logicProps: RelatedErrorsLogicProps = { logUuid, logTimestamp, sessionId }

    return (
        <BindLogic logic={relatedErrorsLogic} props={logicProps}>
            <RelatedErrorsTabContent />
        </BindLogic>
    )
}

function RelatedErrorsTabContent(): JSX.Element {
    const { relatedIssues, relatedIssuesLoading, relatedIssuesError } = useValues(relatedErrorsLogic)
    const { loadRelatedIssues } = useActions(relatedErrorsLogic)

    if (relatedIssuesLoading) {
        return <LoadingState />
    }

    if (relatedIssuesError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadRelatedIssues }}>
                Failed to load related errors
            </LemonBanner>
        )
    }

    if (relatedIssues.length === 0) {
        return <EmptyState />
    }

    return <RelatedIssuesList issues={relatedIssues} />
}

function LoadingState(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonSkeleton className="h-16 w-full" />
            <LemonSkeleton className="h-16 w-full" />
            <LemonSkeleton className="h-16 w-full" />
        </div>
    )
}

function EmptyState(): JSX.Element {
    return (
        <EmptyMessage
            title="No related errors"
            description="No exceptions were found in this session within 6 hours of this log."
            size="small"
        />
    )
}

interface RelatedIssuesListProps {
    issues: MaxErrorTrackingIssuePreview[]
}

function RelatedIssuesList({ issues }: RelatedIssuesListProps): JSX.Element {
    return (
        <div className="flex flex-col">
            <p className="text-muted text-sm mb-2">
                {issues.length} error{issues.length !== 1 ? 's' : ''} found in this session
            </p>
            {issues.map((issue) => (
                <ErrorTrackingIssueCard key={issue.id} issue={issue} showUserCount={false} />
            ))}
        </div>
    )
}
