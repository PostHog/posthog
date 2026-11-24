import {
    ModelCatalogueResponseApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'
import { COST_BASELINE_LABEL, MODELS } from 'products/tasks/frontend/modelCatalog.generated'

import { modelCatalogueLogic } from './modelCatalogueLogic'

export const TEST_MODEL_LISTING: ModelCatalogueResponseApi = {
    cost_baseline: COST_BASELINE_LABEL,
    models: MODELS.map((model) => ({
        runtime_adapter: model.runtimeAdapter as RuntimeAdapterEnumApi,
        model: model.id,
        display_name: model.label,
        supported_efforts: [...model.reasoningEfforts] as ReasoningEffortEnumApi[],
        cost_multiplier: model.costMultiplier ?? null,
        cost_summary: model.costSummary ?? null,
        offered: !model.retired,
    })),
}

export const TEST_MODEL_LISTING_ROUTE = '/api/projects/:team_id/tasks/models/'

export function loadTestModelCatalogue(): void {
    modelCatalogueLogic.mount()
    modelCatalogueLogic.actions.loadListingSuccess(TEST_MODEL_LISTING)
}
