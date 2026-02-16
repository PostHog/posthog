import { InsightEmptyState } from 'scenes/insights/EmptyStates'

export function NoTopLevelTraceEmptyState(): JSX.Element {
    return (
        <InsightEmptyState
            heading="No top-level trace event"
            detail={
                <>
                    This trace doesn't have an associated <code>$ai_trace</code> event.
                    <br />
                    Click on individual generations in the tree to view their content.
                </>
            }
        />
    )
}
