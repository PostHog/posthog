import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { userInterviewTopicsList } from 'products/user_interviews/frontend/generated/api'

import { userInterviewsSetupLogic } from './userInterviewsSetupLogic'

jest.mock('products/user_interviews/frontend/generated/api', () => ({
    userInterviewTopicsList: jest.fn(),
}))

const mockUserInterviewTopicsList = userInterviewTopicsList as jest.MockedFunction<typeof userInterviewTopicsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('userInterviewsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [17, 'has-data'],
    ])('pushes a topic count of %i as status %s', async (count, expected) => {
        mockUserInterviewTopicsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = userInterviewsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.USER_INTERVIEWS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockUserInterviewTopicsList.mockRejectedValue(new Error('network down'))
        const logic = userInterviewsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.USER_INTERVIEWS }).values.status).toBe('unknown')
    })
})
