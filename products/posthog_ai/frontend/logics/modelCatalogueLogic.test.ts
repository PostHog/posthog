import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FALLBACK_MODEL_CHOICES } from '../utils/composerModels'
import { modelCatalogueLogic } from './modelCatalogueLogic'

describe('modelCatalogueLogic', () => {
    const MODELS = [
        {
            runtime_adapter: 'claude' as const,
            model: 'claude-opus-4-8',
            display_name: 'Claude Opus 4.8',
            supported_efforts: ['low' as const, 'high' as const],
        },
        {
            runtime_adapter: 'codex' as const,
            model: 'gpt-5.6-luna',
            display_name: 'GPT-5.6 Luna',
            supported_efforts: ['low' as const, 'high' as const],
        },
    ]

    let logic: ReturnType<typeof modelCatalogueLogic.build>

    function useCatalogueMocks(models: typeof MODELS | 'error'): void {
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/models/': () =>
                    models === 'error' ? [500, { detail: 'gateway down' }] : [200, { models }],
            },
        })
    }

    function mount(): void {
        logic = modelCatalogueLogic()
        logic.mount()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('serves the fetched catalogue and keeps it for the next mount', async () => {
        useCatalogueMocks(MODELS)
        mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogueSuccess']).toMatchValues({ catalogue: MODELS })

        // Remounting renders the stored catalogue right away rather than the built-in stand-in, so the
        // picker doesn't briefly lose the models it was showing a moment ago.
        logic.unmount()
        useCatalogueMocks('error')
        mount()
        expect(logic.values.catalogue).toEqual(MODELS)
    })

    // A failed revalidation must not cost the models we already had — the built-in list is only a
    // stand-in for having nothing at all.
    it.each([['error' as const], [[] as typeof MODELS]])(
        'keeps the stored catalogue when the refetch answers with %s',
        async (response) => {
            useCatalogueMocks(MODELS)
            mount()
            await expectLogic(logic).toDispatchActions(['loadCatalogueSuccess'])
            logic.unmount()

            useCatalogueMocks(response)
            mount()
            await expectLogic(logic).toDispatchActions(['loadCatalogueSuccess']).toMatchValues({ catalogue: MODELS })
        }
    )

    it('falls back to the built-in list when nothing has ever been fetched', async () => {
        useCatalogueMocks('error')
        mount()
        await expectLogic(logic)
            .toDispatchActions(['loadCatalogueSuccess'])
            .toMatchValues({ catalogue: FALLBACK_MODEL_CHOICES })
    })
})
