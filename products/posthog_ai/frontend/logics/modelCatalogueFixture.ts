import tasksModels from '~/mocks/fixtures/api/tasks_models.json'

import { ModelCatalogueResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import { modelCatalogueLogic } from './modelCatalogueLogic'

export const TEST_MODEL_LISTING = tasksModels as ModelCatalogueResponseApi

export const TEST_MODEL_LISTING_ROUTE = '/api/projects/:team_id/tasks/models/'

export function loadTestModelCatalogue(): void {
    modelCatalogueLogic.mount()
    modelCatalogueLogic.actions.loadListingSuccess(TEST_MODEL_LISTING)
}
