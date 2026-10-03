import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { experimentsList } from 'products/experiments/frontend/generated/api'

import { experimentsSetupLogic } from './experimentsSetupLogic'

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsList: jest.fn(),
}))

const mockExperimentsList = experimentsList as jest.MockedFunction<typeof experimentsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('experimentsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    // The list answers archived and non-archived separately, so the count is the sum of both.
    it.each([
        [0, 0, 'needs-setup'],
        [1, 0, 'has-data'],
        [42, 0, 'has-data'],
        [0, 3, 'has-data'],
    ])('pushes %i live and %i archived experiments as status %s', async (live, archived, expected) => {
        mockExperimentsList.mockImplementation((_projectId, params) =>
            Promise.resolve({ count: params?.archived ? archived : live, next: null, previous: null, results: [] })
        )
        const logic = experimentsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockExperimentsList.mockRejectedValue(new Error('network down'))
        const logic = experimentsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS }).values.status).toBe('unknown')
    })
})
