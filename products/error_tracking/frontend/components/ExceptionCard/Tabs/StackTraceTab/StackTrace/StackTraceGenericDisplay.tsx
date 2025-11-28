import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { CollapsibleExceptionList } from 'lib/components/Errors/CollapsibleExceptionList'

import { exceptionCardLogic } from '../../../exceptionCardLogic'

export function StackTraceGenericDisplay({ className }: { className?: string }): JSX.Element {
    const { issueId, showAllFrames } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    return (
        <CollapsibleExceptionList
            showAllFrames={showAllFrames}
            setShowAllFrames={setShowAllFrames}
            className={className}
            onFirstFrameExpanded={() => {
                posthog.capture('error_tracking_stacktrace_explored', { issue_id: issueId })
            }}
        />
    )
}
