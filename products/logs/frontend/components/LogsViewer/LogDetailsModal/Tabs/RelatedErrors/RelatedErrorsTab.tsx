import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { ParsedLogMessage } from 'products/logs/frontend/types'
import { ErrorIssuesList } from 'products/tracing/frontend/components/TraceDrawer/ErrorIssuesList'
import { TraceErrorsScope, traceErrorsLogic } from 'products/tracing/frontend/components/TraceDrawer/traceErrorsLogic'
import { SESSION_ERRORS_WINDOW_HOURS } from 'products/tracing/frontend/errorCorrelation'

import { buildLogErrorsLogicProps } from './buildLogErrorsLogicProps'

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
    return (
        <BindLogic logic={traceErrorsLogic} props={buildLogErrorsLogicProps(log, sessionId)}>
            <RelatedErrorsTabContent initialScope={initialScope} />
        </BindLogic>
    )
}

function RelatedErrorsTabContent({ initialScope }: { initialScope: TraceErrorsScope | null }): JSX.Element {
    const { issues, issuesLoading, issuesFailed, availableScopes, effectiveScope } = useValues(traceErrorsLogic)
    const { loadIssues, setScope } = useActions(traceErrorsLogic)

    // Runs only when the requested scope changes, so a scope the user then picks in the tab stays.
    useEffect(() => {
        if (initialScope && initialScope !== effectiveScope) {
            setScope(initialScope)
        }
    }, [initialScope]) // oxlint-disable-line react-hooks/exhaustive-deps

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
            <ErrorIssuesList
                issues={issues}
                loading={issuesLoading}
                failed={issuesFailed}
                onRetry={loadIssues}
                failedMessage="Failed to load related errors"
                emptyTitle={SCOPES[effectiveScope].emptyTitle}
                emptyDescription={SCOPES[effectiveScope].emptyBody}
                where={SCOPES[effectiveScope].where}
            />
        </div>
    )
}
