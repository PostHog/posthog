import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { failureExcerpt } from '../../lib/ciExplorerDetails'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

const LOG_CLASS =
    'm-0 max-h-60 shrink-0 overflow-auto whitespace-pre-wrap break-words rounded bg-fill-error-tertiary p-3 font-mono text-xs text-danger'

/** Why the focused job failed: the end of its stored failure log, with the lines before it on request. */
export function CIExplorerFailureLog(): JSX.Element {
    const { focusedJobFailure, failureLogs, failureLogsLoading, failureLogsFailed } = useValues(ciExplorerLogic)
    if (failureLogsFailed) {
        return <p className="m-0 text-xs text-secondary">Log unavailable</p>
    }
    if (failureLogs === null || failureLogsLoading) {
        return (
            <p className="m-0 flex items-center gap-2 text-xs text-secondary" role="status">
                <Spinner /> Loading log
            </p>
        )
    }
    const excerpt = focusedJobFailure ? failureExcerpt(focusedJobFailure.lines) : null
    if (!excerpt) {
        return <p className="m-0 text-xs text-secondary">No error excerpt</p>
    }
    return (
        <>
            {/* The column is reversed so the box opens scrolled to its end, where the error is. */}
            <pre className={`${LOG_CLASS} flex flex-col-reverse`} aria-label="Failure excerpt">
                <span>{excerpt.tail}</span>
            </pre>
            {excerpt.context !== null && (
                <details className="text-xs">
                    <summary className="cursor-pointer text-secondary">Log context</summary>
                    <pre className={`${LOG_CLASS} mt-2`}>{excerpt.context}</pre>
                </details>
            )}
        </>
    )
}
