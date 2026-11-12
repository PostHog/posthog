import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { TRACING_DOCS_URL } from 'products/tracing/frontend/traceLinks'

import { exceptionCardLogic } from '../exceptionCardLogic'

export function NoTraceNotice(): JSX.Element {
    const { issueId } = useValues(exceptionCardLogic)

    // pinned: analytics event name, renaming it breaks insights built on it
    useOnMountEffect(() => {
        posthog.capture('error_tracking_trace_tab_no_trace_id', { issue_id: issueId })
    })

    return (
        <div className="flex flex-col gap-1.5 p-4" data-attr="error-tracking-trace-tab-no-trace">
            <span className="font-semibold">No trace linked</span>
            <p className="m-0">
                This exception has no trace ID. An exception links to its trace when your service captures it inside a
                traced request and sends that trace to PostHog.
            </p>
            <div className="text-xs">
                <Link to={TRACING_DOCS_URL} target="_blank" data-attr="error-tracking-trace-tab-no-trace-docs">
                    Send traces to PostHog
                </Link>
            </div>
        </div>
    )
}
