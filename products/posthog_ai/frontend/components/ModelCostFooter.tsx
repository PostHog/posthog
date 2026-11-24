import { useValues } from 'kea'

import { modelCatalogueLogic } from '../logics/modelCatalogueLogic'

export function ModelCostFooter(): JSX.Element {
    const { costBaselineLabel } = useValues(modelCatalogueLogic)
    return (
        <div className="px-2 py-1 text-xxs text-muted" data-attr="model-cost-legend">
            × is cost per token vs {costBaselineLabel}
        </div>
    )
}
