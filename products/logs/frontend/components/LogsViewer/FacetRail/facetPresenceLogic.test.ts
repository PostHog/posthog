import { expectLogic } from 'kea-test-utils'

import { apiMutator } from 'lib/api-orval-mutator'

import { initKeaTests } from '~/test/init'

import { facetPresenceLogic } from './facetPresenceLogic'

jest.mock('lib/api-orval-mutator', () => ({
    __esModule: true,
    apiMutator: jest.fn(),
}))

const mockMutator = jest.mocked(apiMutator)

describe('facetPresenceLogic', () => {
    let logic: ReturnType<typeof facetPresenceLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockMutator.mockResolvedValue({ results: [{ name: 'deployment.environment.name' }], count: 1 })
        logic = facetPresenceLogic({ id: 'test-viewer' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('uses the full presence lookback to discover resource facets', async () => {
        await expectLogic(logic).toDispatchActions(['loadPresentResourceKeysSuccess'])

        expect(mockMutator).toHaveBeenCalledTimes(1)
        const url = new URL(mockMutator.mock.calls[0][0], 'http://localhost')
        expect(JSON.parse(url.searchParams.get('dateRange')!)).toEqual({ date_from: '-90d' })
        expect(url.searchParams.get('attribute_type')).toBe('resource')
        expect(logic.values.visibleFacets.map((facet) => facet.key)).toEqual(['level', 'service', 'environment'])
    })
})
