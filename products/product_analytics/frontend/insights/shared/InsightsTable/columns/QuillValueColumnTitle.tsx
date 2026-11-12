import { formatDateDisplay } from 'lib/components/DateDisplay/formatDateDisplay'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

interface QuillValueColumnTitleProps {
    index: number
    indexedResults: IndexedTrendResult[]
    compare?: boolean | null
    interval?: IntervalType | null
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
}

export function QuillValueColumnTitle({
    index,
    indexedResults,
    compare,
    interval,
    resolvedDateRange,
    timezone,
    weekStartDay,
}: QuillValueColumnTitleProps): JSX.Element {
    const previousResult = compare ? indexedResults.find((r) => r.compare_label === 'previous') : undefined
    const { highlight, primary, secondary } = formatDateDisplay({
        date: (indexedResults[0].dates || indexedResults[0].days)[index],
        secondaryDate: previousResult ? (previousResult.dates || previousResult.days)[index] : undefined,
        interval: interval || 'day',
        resolvedDateRange,
        timezone,
        weekStartDay,
    })

    return (
        <span className="inline-flex items-baseline gap-1" translate="no">
            {highlight && <span className="text-subtle-foreground">{highlight}</span>}
            <span>{primary}</span>
            {secondary !== null && <span>({secondary})</span>}
        </span>
    )
}
