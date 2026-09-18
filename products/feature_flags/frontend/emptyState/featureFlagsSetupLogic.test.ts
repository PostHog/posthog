import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { featureFlagsList } from 'products/feature_flags/frontend/generated/api'

import { featureFlagsSetupLogic } from './featureFlagsSetupLogic'

jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(),
}))

const mockFeatureFlagsList = featureFlagsList as jest.MockedFunction<typeof featureFlagsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('featureFlagsSetupLogic', () => {
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
    ])('pushes %i live and %i archived flags as status %s', async (live, archived, expected) => {
        mockFeatureFlagsList.mockImplementation((_projectId, params) =>
            Promise.resolve({ count: params?.archived ? archived : live, next: null, previous: null, results: [] })
        )
        const logic = featureFlagsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockFeatureFlagsList.mockRejectedValue(new Error('network down'))
        const logic = featureFlagsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe('unknown')
    })
})
