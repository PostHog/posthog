import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { QuillDateColumnTitle } from 'products/product_analytics/frontend/insights/shared/QuillDateColumnTitle'
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

    return (
        <QuillDateColumnTitle
            date={(indexedResults[0].dates || indexedResults[0].days)[index]}
            secondaryDate={previousResult ? (previousResult.dates || previousResult.days)[index] : undefined}
            interval={interval || 'day'}
            resolvedDateRange={resolvedDateRange}
            timezone={timezone}
            weekStartDay={weekStartDay}
        />
    )
}
