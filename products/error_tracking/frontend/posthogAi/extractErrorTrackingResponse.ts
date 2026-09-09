import type { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'

import { parseToolOutputRecord } from 'products/posthog_ai/frontend/api/tools'
import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

const ERROR_TRACKING_RESPONSE_KEYS: readonly (keyof MaxErrorTrackingSearchResponse)[] = [
    'issues',
    'search_query',
    'status',
    'date_from',
    'order_by',
]

/**
 * Error-tracking search output is a `MaxErrorTrackingSearchResponse` (a filters echo plus issue
 * previews) for `ErrorTrackingFiltersWidget`. Outputs that carry none of its fields — e.g. a raw
 * REST issues list — fall back to the generic card instead of rendering empty filter chips.
 */
export function extractErrorTrackingResponse(message: ToolCallMessage): MaxErrorTrackingSearchResponse | null {
    const output = parseToolOutputRecord(message)
    if (!output || !ERROR_TRACKING_RESPONSE_KEYS.some((key) => key in output)) {
        return null
    }
    return output as MaxErrorTrackingSearchResponse
}
