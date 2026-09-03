import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'

import { earlyAccessFeaturesSetupLogic } from './earlyAccessFeaturesSetupLogic'

jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(),
}))

const mockEarlyAccessFeatureList = earlyAccessFeatureList as jest.MockedFunction<typeof earlyAccessFeatureList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('earlyAccessFeaturesSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a feature count of %i as status %s', async (count, expected) => {
        mockEarlyAccessFeatureList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = earlyAccessFeaturesSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.EARLY_ACCESS_FEATURES }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockEarlyAccessFeatureList.mockRejectedValue(new Error('network down'))
        const logic = earlyAccessFeaturesSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.EARLY_ACCESS_FEATURES }).values.status).toBe('unknown')
    })
})
