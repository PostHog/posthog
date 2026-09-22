import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { endpointsList } from 'products/endpoints/frontend/generated/api'

import { endpointsSetupLogic } from './endpointsSetupLogic'

jest.mock('products/endpoints/frontend/generated/api', () => ({
    endpointsList: jest.fn(),
}))

const mockEndpointsList = endpointsList as jest.MockedFunction<typeof endpointsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('endpointsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes an endpoint count of %i as status %s', async (count, expected) => {
        mockEndpointsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = endpointsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENDPOINTS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockEndpointsList.mockRejectedValue(new Error('network down'))
        const logic = endpointsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENDPOINTS }).values.status).toBe('unknown')
    })
})
