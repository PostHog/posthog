import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { pluralize } from 'lib/utils/strings'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'

import { ErrorTrackingIssueCard } from 'products/error_tracking/frontend/ErrorTrackingIssueCard'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { parseLogTimestamp } from 'products/logs/frontend/utils'
import {
    TraceErrorsLogicProps,
    TraceErrorsScope,
    traceErrorsLogic,
} from 'products/tracing/frontend/components/TraceDrawer/traceErrorsLogic'
import { SESSION_ERRORS_WINDOW_HOURS } from 'products/tracing/frontend/errorCorrelation'

const SCOPE_ORDER: TraceErrorsScope[] = ['span', 'trace', 'session']

const SCOPES: Record<
    TraceErrorsScope,
    { label: string; where: string; emptyTitle: string; emptyBody: string; missingId: string }
> = {
    span: {
        label: 'This span',
        where: "in this log's span",
        emptyTitle: 'No errors in this span',
        emptyBody: "No exceptions reported this log's span as the place they were thrown.",
        missingId: 'This log has no span ID',
    },
    trace: {
        label: 'This trace',
        where: "in this log's trace",
        emptyTitle: 'No errors in this trace',
        emptyBody: "No exceptions reported this log's trace as the request they happened in.",
        missingId: 'This log has no trace ID',
    },
    session: {
        label: 'This session',
        where: 'in this session',
        emptyTitle: 'No errors in this session',
        emptyBody: `No exceptions were found in this session within ${SESSION_ERRORS_WINDOW_HOURS} hours of this log.`,
        missingId: 'This log has no session ID. Add one to see errors from the same session.',
    },
}

// A span ID is only unique inside its trace, so the span scope also needs the trace ID. A log with
// a span ID and no trace ID must name the trace ID as the missing one.
function missingIdReason(scope: TraceErrorsScope, availableScopes: TraceErrorsScope[]): string {
    const missingScope = scope === 'span' && !availableScopes.includes('trace') ? 'trace' : scope
    return SCOPES[missingScope].missingId
}

export interface RelatedErrorsTabProps {
    log: ParsedLogMessage
    sessionId: string | null
    initialScope: TraceErrorsScope | null
}

export function RelatedErrorsTab({ log, sessionId, initialScope }: RelatedErrorsTabProps): JSX.Element {
    // Some pipelines send epoch timestamps, which the logic's window would read as an invalid date.
    const timestamp = parseLogTimestamp(log.timestamp)
    const logicProps: TraceErrorsLogicProps = {
        traceId: log.trace_id,
        spanId: log.span_id || null,
        timestamp: timestamp.isValid() ? timestamp.toISOString() : null,
        sessionId,
        initialScope,
    }

    return (
        <BindLogic logic={traceErrorsLogic} props={logicProps}>
            <RelatedErrorsTabContent />
        </BindLogic>
    )
}

function RelatedErrorsTabContent(): JSX.Element {
    const { issues, issuesLoading, issuesFailed, availableScopes, effectiveScope } = useValues(traceErrorsLogic)
    const { loadIssues, setScope } = useActions(traceErrorsLogic)

    if (!effectiveScope) {
        return (
            <div className="flex justify-center w-full py-8">
                <EmptyMessage
                    title="No trace or session ID found"
                    description="To see related errors, include a trace ID or link your logs to session replay with a session ID."
                    buttonText="Learn more"
                    buttonTo="https://posthog.com/docs/logs/link-session-replay"
                    size="small"
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex">
                <LemonSegmentedButton
                    size="small"
                    value={effectiveScope}
                    onChange={(scope) => setScope(scope)}
                    options={SCOPE_ORDER.map((scope) => ({
                        value: scope,
                        label: SCOPES[scope].label,
                        disabledReason: availableScopes.includes(scope)
                            ? undefined
                            : missingIdReason(scope, availableScopes),
                        'data-attr': `logs-related-errors-scope-${scope}`,
                    }))}
                />
            </div>
            <RelatedIssuesList
                issues={issues}
                loading={issuesLoading}
                failed={issuesFailed}
                scope={effectiveScope}
                onRetry={loadIssues}
            />
        </div>
    )
}

function RelatedIssuesList({
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
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-16 w-full" repeat={3} />
            </div>
        )
    }

    if (failed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: onRetry }}>
                Failed to load related errors
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
