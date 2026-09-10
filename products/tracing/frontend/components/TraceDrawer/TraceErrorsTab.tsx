import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { pluralize } from 'lib/utils/strings'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { ErrorTrackingIssueCard } from 'products/posthog_ai/frontend/api/primitives'

import { SESSION_ERRORS_WINDOW_HOURS } from '../../sessionErrors'
import { TraceErrorsLogicProps, traceErrorsLogic } from './traceErrorsLogic'

const TRACING_DOCS_URL = 'https://posthog.com/docs/tracing'

export interface TraceErrorsTabProps {
    traceId: string
    /** Trace start, which anchors the window the exceptions must fall in. */
    timestamp: string | null
    /** The trace's session, or null when the spans resolve to no single session. */
    sessionId: string | null
    /** The spans the session is resolved from are still arriving, so null is not yet an answer. */
    resolving: boolean
}

export function TraceErrorsTab({ traceId, timestamp, sessionId, resolving }: TraceErrorsTabProps): JSX.Element {
    if (resolving) {
        return <LoadingState />
    }

    if (!sessionId) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage
                    title="No session for this trace"
                    description="The spans carry no session ID, or they carry more than one. Add a session ID attribute to your spans to see errors from the same session."
                    buttonText="Learn more"
                    buttonTo={TRACING_DOCS_URL}
                    size="small"
                />
            </div>
        )
    }

    const logicProps: TraceErrorsLogicProps = { traceId, timestamp, sessionId }

    return (
        <BindLogic logic={traceErrorsLogic} props={logicProps}>
            <TraceErrorsTabContent />
        </BindLogic>
    )
}

function TraceErrorsTabContent(): JSX.Element {
    const { sessionIssues, sessionIssuesLoading, sessionIssuesFailed } = useValues(traceErrorsLogic)
    const { loadSessionIssues } = useActions(traceErrorsLogic)

    if (sessionIssuesLoading) {
        return <LoadingState />
    }

    if (sessionIssuesFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSessionIssues }}>
                Could not load the errors for this session.
            </LemonBanner>
        )
    }

    if (sessionIssues.length === 0) {
        return (
            <EmptyMessage
                title="No errors in this session"
                description={`No exceptions were found in this session within ${SESSION_ERRORS_WINDOW_HOURS} hours of this trace.`}
                size="small"
            />
        )
    }

    return <SessionIssuesList issues={sessionIssues} />
}

function LoadingState(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonSkeleton className="h-16 w-full" repeat={3} />
        </div>
    )
}

function SessionIssuesList({ issues }: { issues: MaxErrorTrackingIssuePreview[] }): JSX.Element {
    const totalOccurrences = issues.reduce((sum, issue) => sum + issue.occurrences, 0)
    return (
        <div className="flex flex-col">
            <p className="text-muted text-sm mb-2">
                {pluralize(issues.length, 'issue')} with {pluralize(totalOccurrences, 'occurrence')} in this session
            </p>
            {issues.map((issue) => (
                <ErrorTrackingIssueCard key={issue.id} issue={issue} showUserCount={false} />
            ))}
        </div>
    )
}
