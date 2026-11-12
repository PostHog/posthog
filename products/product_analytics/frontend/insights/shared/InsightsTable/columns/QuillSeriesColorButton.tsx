import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import { resultCustomizationsModalLogic } from '~/queries/nodes/InsightViz/resultCustomizationsModalLogic'

import { QuillSeriesSwatch } from 'products/product_analytics/frontend/insights/shared/QuillSeriesSwatch'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { seriesRowColor } from '../seriesRowColor'

export function QuillSeriesColorButton({ item }: { item: IndexedTrendResult }): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { getTrendsColor } = useValues(trendsDataLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    return (
        <Button
            size="icon-xs"
            aria-label="Change color"
            tooltip="Change color"
            disabledReason={editingDisabledReason}
            onClick={() => openModal(item)}
        >
            <QuillSeriesSwatch color={seriesRowColor(item, getTrendsColor(item))} />
        </Button>
    )
}
