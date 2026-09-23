import { COST_BASELINE_LABEL } from 'products/tasks/frontend/modelCatalog.generated'

export function ModelCostFooter(): JSX.Element {
    return (
        <div className="px-2 py-1 text-xxs text-muted" data-attr="model-cost-legend">
            × is cost per token vs {COST_BASELINE_LABEL}
        </div>
    )
}
