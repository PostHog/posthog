import { DataToolRow, GenericMcpToolRenderer, type ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { ErrorTrackingFiltersWidget } from './ErrorTrackingFiltersWidget'
import { extractErrorTrackingResponse } from './extractErrorTrackingResponse'

/**
 * Error-tracking search / filter tool calls. `rawOutput` is a `MaxErrorTrackingSearchResponse`
 * directly; `ErrorTrackingFiltersWidget` renders the filter chips + paginated issue list (and
 * pushes filters into the error-tracking scene when it is active). Pre-completion or missing output
 * falls back to the generic card.
 */
export function ErrorTrackingWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const filters = message.status === 'completed' ? extractErrorTrackingResponse(message) : null

    if (!filters) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <DataToolRow {...props}>
            <ErrorTrackingFiltersWidget toolCallId={message.id} filters={filters} />
        </DataToolRow>
    )
}
