import { useCallback } from 'react'

import type { DateRangeZoomData } from '@posthog/quill-charts'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

/** Maps the quill chart's drag-to-zoom callback onto the host's `context.onDateRangeZoom`,
 *  translating dragged label indices into the result's ISO day strings. Returns undefined when
 *  zooming is unavailable — drag-to-zoom is opt-in: it only surfaces where the host passes a
 *  handler (the insight scene, web analytics tiles), never on dashboard cards or read-only embeds. */
export function useTrendsDateRangeZoom(
    context: QueryContext<InsightVizNode> | undefined,
    days: string[] | undefined
): ((data: DateRangeZoomData) => void) | undefined {
    const contextZoom = context?.onDateRangeZoom

    const handler = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData) => {
            const dateFrom = days?.[startIndex]
            const dateTo = days?.[endIndex]
            if (dateFrom && dateTo) {
                contextZoom?.(dateFrom, dateTo)
            }
        },
        [days, contextZoom]
    )

    return contextZoom && days?.length ? handler : undefined
}
