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
    // resource-attribute facet. The failure has to stay visible through the retry, including while it
    // is in flight, so a stalled retry cannot make the incomplete rail look healthy again.
    it('keeps the failure flag raised through an in-flight retry and clears it only on success', async () => {
        mockAttributes.mockRejectedValueOnce(new Error('Malformed JSON response'))
        logic = facetPresenceLogic({ id: 'test-viewer' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ presenceLoadFailed: true })

        // Hold the retry in flight: the banner is gated on the flag, so the flag must stay raised
        // (and the loader must report loading) until the retry actually resolves.
        type AttributesResponse = Awaited<ReturnType<typeof logsAttributesRetrieve>>
        let resolveRetry!: (value: AttributesResponse) => void
        mockAttributes.mockReturnValueOnce(
            new Promise<AttributesResponse>((resolve) => {
                resolveRetry = resolve
            })
        )
        logic.actions.loadPresentResourceKeys()

        await expectLogic(logic).toMatchValues({ presenceLoadFailed: true, presentResourceKeysLoading: true })

        resolveRetry({
            results: [
                {
                    name: 'service.name',
                    propertyFilterType: 'log_resource_attribute',
                    matchedOn: MatchedOnEnumApi.Key,
                },
            ],
            count: 1,
        })

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ presenceLoadFailed: false, presentResourceKeys: ['service.name'] })
    })
})
