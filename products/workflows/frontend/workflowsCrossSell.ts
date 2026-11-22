import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export function recordCrossSellFromWorkflows(to: ProductKey, intentContext: ProductIntentContext): void {
    void addProductIntentForCrossSell({ from: ProductKey.WORKFLOWS, to, intent_context: intentContext }).catch(
        () => null
    )
}
