import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productToursList } from 'products/product_tours/frontend/generated/api'

import { productToursSetupLogic } from './productToursSetupLogic'

jest.mock('products/product_tours/frontend/generated/api', () => ({
    productToursList: jest.fn(),
    productToursCreate: jest.fn(),
}))

const mockProductToursList = productToursList as jest.MockedFunction<typeof productToursList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('productToursSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a tour count of %i as status %s', async (count, expected) => {
        mockProductToursList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = productToursSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PRODUCT_TOURS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockProductToursList.mockRejectedValue(new Error('network down'))
        const logic = productToursSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PRODUCT_TOURS }).values.status).toBe('unknown')
    })
})
