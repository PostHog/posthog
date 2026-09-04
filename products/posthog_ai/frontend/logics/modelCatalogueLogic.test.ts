import { initKeaTests } from '~/test/init'

import { MODELS } from 'products/tasks/frontend/modelCatalog.generated'

import { modelCatalogueLogic } from './modelCatalogueLogic'

describe('modelCatalogueLogic', () => {
    let logic: ReturnType<typeof modelCatalogueLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = modelCatalogueLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('offers every catalog model under the name the catalog gives it', () => {
        expect(logic.values.catalogue.map((choice) => [choice.model, choice.display_name])).toEqual(
            MODELS.map((model) => [model.id, model.label])
        )
    })

    // An empty effort list is an answer, not missing metadata: the picker renders such a model with no
    // effort dropdown, and a run must not send an effort for it. Filling the gap with a default would
    // offer efforts the backend rejects.
    it('keeps the effort list empty for a model with no effort control', () => {
        const withoutEfforts = MODELS.filter((model) => model.reasoningEfforts.length === 0).map((model) => model.id)
        expect(withoutEfforts.length).toBeGreaterThan(0)

        for (const model of withoutEfforts) {
            expect(logic.values.catalogue.find((choice) => choice.model === model)?.supported_efforts).toEqual([])
        }
    })
})
