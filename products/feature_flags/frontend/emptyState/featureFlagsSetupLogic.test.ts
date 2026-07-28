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

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a flag count of %i as status %s', async (count, expected) => {
        mockFeatureFlagsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
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
