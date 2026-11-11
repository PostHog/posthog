import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import { resultCustomizationsModalLogic } from '~/queries/nodes/InsightViz/resultCustomizationsModalLogic'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { seriesRowColor } from '../seriesRowColor'

export function QuillSeriesColorButton({ item }: { item: IndexedTrendResult }): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { getTrendsColor } = useValues(trendsDataLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))
    const color = seriesRowColor(item, getTrendsColor(item))

    return (
        <Button
            size="icon-xs"
            aria-label="Change color"
            tooltip="Change color"
            disabledReason={editingDisabledReason}
            onClick={() => openModal(item)}
        >
            <span
                className="size-3.5 rounded-full border-2"
                // The series color comes from the chart's palette or the user's choice, so it can't be a token.
                // eslint-disable-next-line react/forbid-dom-props
                style={{ borderColor: color, backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)` }}
            />
        </Button>
    )
}
