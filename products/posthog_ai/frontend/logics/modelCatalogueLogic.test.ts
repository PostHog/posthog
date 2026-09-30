import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { MODELS } from 'products/tasks/frontend/modelCatalog.generated'

import { modelCatalogueLogic } from './modelCatalogueLogic'

const GATED_ONE = { id: 'acme/gated-one', flag: 'acme-gated-one' }
const GATED_TWO = { id: 'acme/gated-two', flag: 'acme-gated-two' }

// The catalog gates no model at the moment, so the gate needs stand-ins to be exercised at
// all. Two of them, because one cannot show that a flag reveals its own model and no other.
// Naming real models here instead is what tied these cases to a rollout that ends: the
// open-weights models stayed hidden after their flags had reached everyone.
jest.mock('products/tasks/frontend/modelCatalog.generated', () => {
    const actual = jest.requireActual('products/tasks/frontend/modelCatalog.generated')
    return {
        ...actual,
        MODELS: [
            ...actual.MODELS,
            {
                id: 'acme/gated-one',
                runtimeAdapter: 'claude',
                reasoningEfforts: [],
                label: 'Gated one',
                accessFlag: 'acme-gated-one',
            },
            {
                id: 'acme/gated-two',
                runtimeAdapter: 'claude',
                reasoningEfforts: [],
                label: 'Gated two',
                accessFlag: 'acme-gated-two',
            },
        ],
    }
})

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
        mountWithFlags([GATED_ONE.flag])

        const offered = logic.values.catalogue.map((choice) => choice.model)
        expect(offered).toContain(GATED_ONE.id)
        expect(offered).not.toContain(GATED_TWO.id)
    })

    // These run on the claude harness and are offered to everyone. Every gate that reads an
    // access flag fails closed, so a flag left on the catalog row after its rollout finished
    // took them off the composer for anyone the flag service could not answer for.
    it.each([
        'deepseek-ai/deepseek-v4-flash-0731',
        '@cf/zai-org/glm-5.2',
        'zai-org/glm-5.3',
        'zai-org/glm-5.3-flash',
        'moonshotai/kimi-k3',
    ])('offers %s without a flag', (model: string) => {
        mountWithFlags([])

        expect(logic.values.catalogue.map((choice) => choice.model)).toContain(model)
    })

    // A run already on a retired model keeps its name and its full effort range, which it reads off the
    // catalogue. `pickerModels` is what drops retired models from the list a person picks from.
    it('keeps a retired model in the catalogue', () => {
        const retired = MODELS.filter((model) => model.retired)
        expect(retired.length).toBeGreaterThan(0)
        mountWithFlags(GATED.map((model) => model.accessFlag as string))

        const known = logic.values.catalogue.map((choice) => choice.model)
        for (const model of retired) {
            expect(known).toContain(model.id)
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
