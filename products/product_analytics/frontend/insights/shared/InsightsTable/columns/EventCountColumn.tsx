import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

type EventCountColumnTitleProps = {
    title: string
}

export function EventCountColumnTitle({ title }: EventCountColumnTitleProps): JSX.Element {
    return (
        <Tooltip title="The events that all series counted for this value. The rows are the values with the most events.">
            <span>{title}</span>
        </Tooltip>
    )
}

type EventCountColumnItemProps = {
    item: IndexedTrendResult
}

export function EventCountColumnItem({ item }: EventCountColumnItemProps): JSX.Element {
    return <span>{item.breakdown_event_count == null ? '—' : humanFriendlyNumber(item.breakdown_event_count)}</span>
}
