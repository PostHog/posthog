import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { MODELS } from 'products/tasks/frontend/modelCatalog.generated'

import { modelCatalogueLogic } from './modelCatalogueLogic'

describe('modelCatalogueLogic', () => {
    let logic: ReturnType<typeof modelCatalogueLogic.build>

    const GATED = MODELS.filter((model) => model.accessFlag)
    const UNGATED = MODELS.filter((model) => !model.accessFlag)

    function mountWithFlags(flags: string[]): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        logic = modelCatalogueLogic()
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('offers every catalog model under the name the catalog gives it', () => {
        mountWithFlags(GATED.map((model) => model.accessFlag as string))

        expect(logic.values.catalogue.map((choice) => [choice.model, choice.display_name])).toEqual(
            MODELS.map((model) => [model.id, model.label])
        )
    })

    // A staged model is a picker offering the run API would reject, so it stays hidden until
    // the person holds its flag. The API is still the gate — this only stops us offering it.
    it('hides a model whose access flag the person does not hold', () => {
        expect(GATED.length).toBeGreaterThan(0)
        mountWithFlags([])

        const offered = logic.values.catalogue.map((choice) => choice.model)
        expect(offered).toEqual(UNGATED.map((model) => model.id))
    })

    it('reveals only the gated model whose flag is on', () => {
        const [first] = GATED
        mountWithFlags([first.accessFlag as string])

        const offered = logic.values.catalogue.map((choice) => choice.model)
        expect(offered).toContain(first.id)
        for (const model of GATED.filter((candidate) => candidate.id !== first.id)) {
            expect(offered).not.toContain(model.id)
        }
    })

    // An empty effort list is an answer, not missing metadata: the picker renders such a model with no
    // effort dropdown, and a run must not send an effort for it. Filling the gap with a default would
    // offer efforts the backend rejects.
    it('keeps the effort list empty for a model with no effort control', () => {
        const withoutEfforts = MODELS.filter((model) => model.reasoningEfforts.length === 0)
        expect(withoutEfforts.length).toBeGreaterThan(0)
        mountWithFlags(GATED.map((model) => model.accessFlag as string))

        for (const model of withoutEfforts) {
            expect(logic.values.catalogue.find((choice) => choice.model === model.id)?.supported_efforts).toEqual([])
        }
    })
})
