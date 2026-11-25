import { Text } from '@posthog/quill'

import { COST_BASELINE_LABEL } from 'products/tasks/frontend/modelCatalog.generated'

export function QuillModelCostFooter(): JSX.Element {
    return (
        <Text
            size="xxs"
            variant="muted"
            className="px-2 py-1"
            data-attr="model-cost-legend"
            render={<div className="m-0" />}
        >
            × is cost per token vs {COST_BASELINE_LABEL}
        </Text>
    )
}
