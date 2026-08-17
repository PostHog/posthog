import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { userInterviewTopicsList, userInterviewsList } from 'products/user_interviews/frontend/generated/api'

import { userInterviewsSetupLogic } from './userInterviewsSetupLogic'

jest.mock('products/user_interviews/frontend/generated/api', () => ({
    userInterviewTopicsList: jest.fn(),
    userInterviewsList: jest.fn(),
}))

const mockUserInterviewTopicsList = userInterviewTopicsList as jest.MockedFunction<typeof userInterviewTopicsList>
const mockUserInterviewsList = userInterviewsList as jest.MockedFunction<typeof userInterviewsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('userInterviewsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    // Responses outlive their topic, so the count is the sum of topics and interviews.
    it.each([
        [0, 0, 'needs-setup'],
        [1, 0, 'has-data'],
        [17, 0, 'has-data'],
        [0, 4, 'has-data'],
    ])('pushes %i topics and %i interviews as status %s', async (topics, interviews, expected) => {
        mockUserInterviewTopicsList.mockResolvedValue({ count: topics, next: null, previous: null, results: [] })
        mockUserInterviewsList.mockResolvedValue({ count: interviews, next: null, previous: null, results: [] })
        const logic = userInterviewsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.USER_INTERVIEWS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockUserInterviewTopicsList.mockRejectedValue(new Error('network down'))
        mockUserInterviewsList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        const logic = userInterviewsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.USER_INTERVIEWS }).values.status).toBe('unknown')
    })
})
