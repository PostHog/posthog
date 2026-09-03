import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAttributesRetrieve } from 'products/logs/frontend/generated/api'
import { MatchedOnEnumApi } from 'products/logs/frontend/generated/api.schemas'
import { userFacetSettingsRetrieve } from 'products/platform_features/frontend/generated/api'

import { facetPresenceLogic } from './facetPresenceLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAttributesRetrieve: jest.fn(),
}))
jest.mock('products/platform_features/frontend/generated/api', () => ({
    __esModule: true,
    userFacetSettingsRetrieve: jest.fn(),
    userFacetSettingsPartialUpdate: jest.fn(),
}))

const mockAttributes = logsAttributesRetrieve as jest.MockedFunction<typeof logsAttributesRetrieve>
const mockFacetSettings = userFacetSettingsRetrieve as jest.MockedFunction<typeof userFacetSettingsRetrieve>

describe('facetPresenceLogic', () => {
    let logic: ReturnType<typeof facetPresenceLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockFacetSettings.mockResolvedValue({ custom_facets: [] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // A failed probe used to render a rail that looks complete but is missing every
    // resource-attribute facet, so the failure has to be visible and the retry has to clear it.
    it('flags a failed presence probe until a retry succeeds', async () => {
        mockAttributes.mockRejectedValueOnce(new Error('Malformed JSON response'))
        logic = facetPresenceLogic({ id: 'test-viewer' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ presenceLoadFailed: true })

        mockAttributes.mockResolvedValue({
            results: [
                {
                    name: 'service.name',
                    propertyFilterType: 'log_resource_attribute',
                    matchedOn: MatchedOnEnumApi.Key,
                },
            ],
            count: 1,
        })
        logic.actions.loadPresentResourceKeys()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ presenceLoadFailed: false, presentResourceKeys: ['service.name'] })
    })
})
