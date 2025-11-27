import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'

import { cancelEvent } from '../../../utils'
import { exceptionCardLogic } from '../exceptionCardLogic'

export function StacktraceGenericDisplay({ className }: { className?: string }): JSX.Element {
    const { issueId, showAllFrames } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    return (
        <ChainedStackTraces
            showAllFrames={showAllFrames}
            setShowAllFrames={setShowAllFrames}
            className={className}
            onFrameContextClick={(_, e) => cancelEvent(e)}
            onFirstFrameExpanded={() => {
                posthog.capture('error_tracking_stacktrace_explored', { issue_id: issueId })
            }}
        />
    )
}
