import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { pluralize } from 'lib/utils/strings'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { ErrorTrackingIssueCard } from 'products/error_tracking/frontend/ErrorTrackingIssueCard'

import { SESSION_ERRORS_WINDOW_HOURS } from '../../errorCorrelation'
import { TRACING_DOCS_URL } from '../../traceLinks'
import { TraceErrorsLogicProps, TraceErrorsScope, traceErrorsLogic } from './traceErrorsLogic'

// Every string a scope needs, so adding one is a single entry and the Record keeps it exhaustive.
const SCOPES: Record<TraceErrorsScope, { label: string; where: string; emptyTitle: string; emptyBody: string }> = {
    span: {
        label: 'This span',
        where: 'in this span',
        emptyTitle: 'No errors in this span',
        emptyBody: 'No exceptions reported this span as the place they were thrown.',
    },
    trace: {
        label: 'This trace',
        where: 'in this trace',
        emptyTitle: 'No errors in this trace',
        emptyBody: 'No exceptions reported this trace as the request they happened in.',
    },
    session: {
        label: 'This session',
        where: 'in this session',
        emptyTitle: 'No errors in this session',
        emptyBody: `No exceptions were found in this session within ${SESSION_ERRORS_WINDOW_HOURS} hours of this trace.`,
    },
}

export interface TraceErrorsTabProps {
    traceId: string
    /** The inspected span, which the span scope matches on. */
    spanId: string | null
    /** Trace start, which anchors the window the exceptions must fall in. */
    timestamp: string | null
    /** The trace's session, or null when the spans resolve to no single session. */
    sessionId: string | null
    /** The scope to open on, when the caller named one. A badge names the tier it counted. */
    initialScope: TraceErrorsScope | null
    /** The spans the session is resolved from are still arriving, so a null session is not yet an answer. */
    resolving: boolean
}

export function TraceErrorsTab({
    traceId,
    spanId,
    timestamp,
    sessionId,
    initialScope,
    resolving,
}: TraceErrorsTabProps): JSX.Element {
    // Only the session scope waits. The trace and span scopes read ids the clicked row already
    // carries, so holding the whole tab for a session resolve would delay the precise answer for
    // the fuzzy one.
    if (resolving && !traceId) {
        return <LoadingState />
    }

    const logicProps: TraceErrorsLogicProps = { traceId, spanId, timestamp, sessionId, initialScope }

    return (
        <BindLogic logic={traceErrorsLogic} props={logicProps}>
            <TraceErrorsTabContent />
        </BindLogic>
    )
}

function TraceErrorsTabContent(): JSX.Element {
    const { issues, issuesLoading, issuesFailed, availableScopes, effectiveScope } = useValues(traceErrorsLogic)
    const { loadIssues, setScope } = useActions(traceErrorsLogic)

    if (!effectiveScope) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage
                    title="No trace or session to match errors on"
                    description="This span carries no trace ID, and the spans carry no session ID. Add a session ID attribute to your spans to see errors from the same session."
                    buttonText="Learn more"
                    buttonTo={TRACING_DOCS_URL}
                    size="small"
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {availableScopes.length > 1 && (
                <div className="flex">
                    <LemonSegmentedButton
                        size="small"
                        value={effectiveScope}
                        onChange={(scope) => setScope(scope as TraceErrorsScope)}
                        options={availableScopes.map((scope) => ({
                            value: scope,
                            label: SCOPES[scope].label,
                            'data-attr': `tracing-trace-errors-scope-${scope}`,
                        }))}
                    />
                </div>
            )}
            <TraceErrorsList
                issues={issues}
                loading={issuesLoading}
                failed={issuesFailed}
                scope={effectiveScope}
                onRetry={loadIssues}
            />
        </div>
    )
}

function TraceErrorsList({
    issues,
    loading,
    failed,
    scope,
    onRetry,
}: {
    issues: MaxErrorTrackingIssuePreview[]
    loading: boolean
    failed: boolean
    scope: TraceErrorsScope
    onRetry: () => void
}): JSX.Element {
    if (loading) {
        return <LoadingState />
    }

    if (failed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: onRetry }}>
                Could not load the errors for this trace.
            </LemonBanner>
        )
    }

    if (issues.length === 0) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage title={SCOPES[scope].emptyTitle} description={SCOPES[scope].emptyBody} size="small" />
            </div>
        )
    }

    const totalOccurrences = issues.reduce((sum, issue) => sum + issue.occurrences, 0)
    return (
        <div className="flex flex-col">
            <p className="text-muted text-sm mb-2">
                {pluralize(issues.length, 'issue')} with {pluralize(totalOccurrences, 'occurrence')}{' '}
                {SCOPES[scope].where}
            </p>
            {issues.map((issue) => (
                <ErrorTrackingIssueCard key={issue.id} issue={issue} showUserCount={false} />
            ))}
        </div>
    )
}

function LoadingState(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonSkeleton className="h-16 w-full" repeat={3} />
        </div>
    )
}
