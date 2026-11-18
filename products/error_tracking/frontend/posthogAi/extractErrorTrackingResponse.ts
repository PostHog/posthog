import type { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'

import { getToolOutputRecord } from 'products/posthog_ai/frontend/api/tools'
import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

// Fields only a search response carries. `status` is excluded on purpose: an issue detail echoes it
// too, so matching on it would render that detail as an empty issue list.
const ERROR_TRACKING_RESPONSE_KEYS: readonly (keyof MaxErrorTrackingSearchResponse)[] = [
    'issues',
    'search_query',
    'date_from',
    'order_by',
]

/**
 * Error-tracking search output is a `MaxErrorTrackingSearchResponse` (a filters echo plus issue
 * previews) for `ErrorTrackingFiltersWidget`. Outputs that carry none of those fields — e.g. a raw
 * REST issues list, or one issue's details — fall back to the generic card instead of rendering
 * empty filter chips.
 */
export function extractErrorTrackingResponse(message: ToolCallMessage): MaxErrorTrackingSearchResponse | null {
    const output = getToolOutputRecord(message)
    if (!output || !ERROR_TRACKING_RESPONSE_KEYS.some((key) => key in output)) {
        return null
    }
    return output as MaxErrorTrackingSearchResponse
}
