import { Text } from '@posthog/quill'

import { COST_BASELINE_LABEL } from 'products/tasks/frontend/modelCatalog.generated'

import { getModelCost } from '../utils/composerModels'

/**
 * The rates sit in a native `title` rather than a `Tooltip`: this renders inside select items, and a portalled
 * tooltip competes with the popup's focus handling.
 */
export function QuillModelCostChip({ model }: { model: string }): JSX.Element | null {
    const cost = getModelCost(model)

    if (!cost) {
        return null
    }

    return (
        <Text
            size="xs"
            variant="muted"
            className="tabular-nums whitespace-nowrap"
            title={`Cost per token vs ${COST_BASELINE_LABEL}. ${cost.summary}`}
            data-attr="model-cost-multiplier"
            render={<span className="m-0" />}
        >
            {cost.multiplier}
        </Text>
    )
}
