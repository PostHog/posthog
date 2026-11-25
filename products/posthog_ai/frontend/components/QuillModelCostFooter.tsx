import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { modelCatalogueLogic } from '../logics/modelCatalogueLogic'

export function QuillModelCostFooter(): JSX.Element {
    const { costBaselineLabel } = useValues(modelCatalogueLogic)
    return (
        <Text
            size="xxs"
            variant="muted"
            className="px-2 py-1"
            data-attr="model-cost-legend"
            render={<div className="m-0" />}
        >
            × is cost per token vs {costBaselineLabel}
        </Text>
    )
}
