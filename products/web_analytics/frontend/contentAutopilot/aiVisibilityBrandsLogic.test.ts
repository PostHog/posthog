import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoBrandsList, aeoBrandsPartialUpdate } from '../generated/api'
import type { AEOBrandApi } from '../generated/api.schemas'
import { aiVisibilityBrandsLogic } from './aiVisibilityBrandsLogic'

jest.mock('../generated/api', () => ({
    aeoBrandsList: jest.fn(),
    aeoBrandsPartialUpdate: jest.fn(),
}))

const BRAND: AEOBrandApi = {
    id: '00000000-0000-4000-8000-000000000701',
    name: 'Rival',
    domain: 'rival.example.org',
    kind: 'unknown',
    status: 'suggested',
    source: 'citations',
    aliases: [],
    created_at: '2026-11-01T00:00:00Z',
    updated_at: null,
}

describe('aiVisibilityBrandsLogic', () => {
    let logic: ReturnType<typeof aiVisibilityBrandsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoBrandsList).mockResolvedValue({ count: 1, next: null, previous: null, results: [BRAND] })
        jest.mocked(aeoBrandsPartialUpdate).mockResolvedValue({ ...BRAND, kind: 'competitor', status: 'confirmed' })
        logic = aiVisibilityBrandsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('confirms a brand in the same call that labels it, then reloads the page', async () => {
        await expectLogic(logic).toDispatchActions(['loadBrandsSuccess'])

        logic.actions.labelBrand(BRAND.id, 'competitor')

        await expectLogic(logic).toDispatchActions(['updateBrandSuccess'])
        // The saved brand shows before the reload, so the row never unlocks with stale values.
        expect(logic.values.brands?.results[0]).toMatchObject({ kind: 'competitor', status: 'confirmed' })
        await expectLogic(logic).toDispatchActions(['loadBrandsSuccess'])
        expect(aeoBrandsPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), BRAND.id, {
            kind: 'competitor',
            status: 'confirmed',
        })
        expect(logic.values.updatingIds).toEqual([])
    })
})
