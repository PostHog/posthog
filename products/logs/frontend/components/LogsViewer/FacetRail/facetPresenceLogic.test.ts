import { expectLogic } from 'kea-test-utils'

import { apiMutator } from 'lib/api-orval-mutator'

import { initKeaTests } from '~/test/init'

import { facetPresenceLogic } from './facetPresenceLogic'

// Mock the transport, not the generated client: the real logsAttributesRetrieve still builds the
// request URL, so the test sees exactly what the backend would receive.
jest.mock('lib/api-orval-mutator', () => ({
    __esModule: true,
    apiMutator: jest.fn(),
}))

const mockMutator = apiMutator as jest.MockedFunction<typeof apiMutator>

const ID = 'test-viewer'

describe('facetPresenceLogic', () => {
    let logic: ReturnType<typeof facetPresenceLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockMutator.mockResolvedValue({ results: [], count: 0 })
        logic = facetPresenceLogic({ id: ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // Regression: the presence probe used to send the range as a raw object, which the URL builder
    // rendered as "dateRange=[object Object]" and the backend could not parse — so no facets rendered.
    it('sends the lookback range as parseable JSON, not [object Object]', async () => {
        await expectLogic(logic).toDispatchActions(['loadPresentResourceKeysSuccess'])

        expect(mockMutator).toHaveBeenCalledTimes(1)
        const requestUrl = mockMutator.mock.calls[0][0]
        const dateRange = new URL(requestUrl, 'http://localhost').searchParams.get('dateRange')
        expect(JSON.parse(dateRange!)).toEqual({ date_from: '-90d' })
    })
})
