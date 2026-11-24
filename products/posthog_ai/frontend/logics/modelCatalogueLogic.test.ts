import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ModelCatalogueResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import { modelCatalogueLogic } from './modelCatalogueLogic'

const LISTING: ModelCatalogueResponseApi = {
    cost_baseline: 'Claude Sonnet 5',
    models: [
        {
            runtime_adapter: 'claude',
            model: 'claude-opus-5-5',
            display_name: 'Claude Opus 5.5',
            supported_efforts: ['low', 'high'],
            cost_multiplier: '2×',
            cost_summary: 'Input $4 · Output $20 per 1M tokens',
            offered: true,
        },
        {
            runtime_adapter: 'codex',
            model: 'gpt-6-sol',
            display_name: 'GPT-6 Sol',
            supported_efforts: [],
            cost_multiplier: null,
            cost_summary: null,
            offered: false,
        },
    ],
}

describe('modelCatalogueLogic', () => {
    let logic: ReturnType<typeof modelCatalogueLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('reads the model list from the backend, older versions included', async () => {
        let includeUnoffered: string | null = null
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/models/': ({ request }) => {
                    includeUnoffered = new URL(request.url).searchParams.get('include_unoffered')
                    return [200, LISTING]
                },
            },
        })
        initKeaTests()
        logic = modelCatalogueLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadListingSuccess'])

        expect(includeUnoffered).toEqual('true')
        expect(logic.values.catalogue).toEqual(LISTING.models)
        expect(logic.values.costBaselineLabel).toEqual('Claude Sonnet 5')
    })

    it('offers no model when the request fails', async () => {
        useMocks({ get: { '/api/projects/:team_id/tasks/models/': () => [500, {}] } })
        initKeaTests()
        logic = modelCatalogueLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadListingFailure'])

        expect(logic.values.catalogue).toEqual([])
    })
})
