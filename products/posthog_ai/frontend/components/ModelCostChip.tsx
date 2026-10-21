import { COST_BASELINE_LABEL } from 'products/tasks/frontend/modelCatalog.generated'

import { getModelCost } from '../utils/composerModels'

export interface ModelCostChipProps {
    model: string
}

/**
 * The rates sit in a native `title` rather than a `Tooltip`: this renders inside menu items in
 * two different menu systems, and a portalled tooltip competes with each one's focus handling.
 */
export function ModelCostChip({ model }: ModelCostChipProps): JSX.Element | null {
    const cost = getModelCost(model)
    if (!cost) {
        return null
    }
    return (
        <span
            className="text-xs tabular-nums whitespace-nowrap text-muted"
            title={`Cost per token vs ${COST_BASELINE_LABEL}. ${cost.summary}`}
            data-attr="model-cost-multiplier"
        >
            {cost.multiplier}
        </span>
    )
}
