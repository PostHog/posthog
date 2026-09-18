import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    userFacetSettingsPartialUpdate,
    userFacetSettingsRetrieve,
} from 'products/platform_features/frontend/generated/api'
import { UserFacetSettingsEntrySourceTypeEnumApi } from 'products/platform_features/frontend/generated/api.schemas'

import { customFacetsLogic } from './customFacetsLogic'

jest.mock('products/platform_features/frontend/generated/api', () => ({
    __esModule: true,
    userFacetSettingsRetrieve: jest.fn(),
    userFacetSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieve = userFacetSettingsRetrieve as jest.MockedFunction<typeof userFacetSettingsRetrieve>
const mockPartialUpdate = userFacetSettingsPartialUpdate as jest.MockedFunction<typeof userFacetSettingsPartialUpdate>

describe('customFacetsLogic', () => {
    // A singleton logic (no `key`) — each test sets up its mocks, then mounts fresh via `mount()`
    // below. Mounting inside `beforeEach` would fire `afterMount` before a test's own mock override
    // took effect, since re-calling the wrapper mid-test returns the same already-mounted instance.
    let logic: ReturnType<typeof customFacetsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOM_FACET_PINNING]: true })
        mockRetrieve.mockResolvedValue({ custom_facets: [] })
        mockPartialUpdate.mockImplementation(async (_uuid, _params, body) => ({
            custom_facets: body?.custom_facets ?? [],
        }))
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mount(): ReturnType<typeof customFacetsLogic.build> {
        logic = customFacetsLogic()
        logic.mount()
        return logic
    }

    it('does not load or expose custom facets when the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockRetrieve).not.toHaveBeenCalled()
        expect(logic.values.customFacets).toEqual([])
    })

    it('loads entries when the flag arrives after mount', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        mount()
        expect(mockRetrieve).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOM_FACET_PINNING]: true })
        await expectLogic(logic).toDispatchActions(['loadEntries', 'loadEntriesSuccess'])
    })

    it('mutations build on the persisted list when entries have not loaded yet', async () => {
        // A PATCH replaces the whole server-side list — building it on unloaded local state would
        // wipe every facet the user pinned elsewhere.
        featureFlagLogic.actions.setFeatureFlags([], {})
        mockRetrieve.mockResolvedValue({
            custom_facets: [
                { key: 'pinned.elsewhere', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute },
            ],
        })
        mount()
        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        expect(mockPartialUpdate).toHaveBeenCalledWith(
            '@me',
            { product: 'logs' },
            {
                custom_facets: [
                    { key: 'pinned.elsewhere', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute },
                    { key: 'log.iostream', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute },
                ],
            }
        )
    })

    it('loads persisted entries on mount and exposes them as facet configs', async () => {
        mockRetrieve.mockResolvedValue({
            custom_facets: [{ key: 'log.iostream', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute }],
        })
        mount()
        await expectLogic(logic).toDispatchActions(['loadEntriesSuccess'])

        expect(logic.values.customFacets).toEqual([
            expect.objectContaining({
                key: 'custom:attribute:log.iostream',
                source: { type: 'attribute', key: 'log.iostream' },
            }),
        ])
    })

    it('adding a facet persists the full updated list and updates local state', async () => {
        mount()
        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        expect(logic.values.entries).toEqual([
            { key: 'log.iostream', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute },
        ])
        expect(mockPartialUpdate).toHaveBeenCalledWith(
            '@me',
            { product: 'logs' },
            { custom_facets: [{ key: 'log.iostream', source_type: UserFacetSettingsEntrySourceTypeEnumApi.Attribute }] }
        )
    })

    it('adding the same key and sourceType twice does not duplicate or persist again', async () => {
        mount()
        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])
        mockPartialUpdate.mockClear()

        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        expect(logic.values.entries).toHaveLength(1)
        expect(mockPartialUpdate).not.toHaveBeenCalled()
    })

    it('removing a facet only drops the matching key+sourceType pair', async () => {
        // The same key can exist as both an attribute and a resource-attribute facet — removing one
        // must not also remove the other.
        mount()
        logic.actions.addCustomFacet('environment', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])
        logic.actions.addCustomFacet('environment', 'resourceAttribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        logic.actions.removeCustomFacet('environment', 'attribute')
        await expectLogic(logic).toDispatchActions(['removeCustomFacetSuccess'])

        expect(logic.values.entries).toEqual([
            { key: 'environment', source_type: UserFacetSettingsEntrySourceTypeEnumApi.ResourceAttribute },
        ])
    })
})
