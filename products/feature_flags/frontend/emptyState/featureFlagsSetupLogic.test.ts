import { getContext } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { featureFlagsList } from 'products/feature_flags/frontend/generated/api'

import { featureFlagsSetupLogic } from './featureFlagsSetupLogic'

jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(),
}))

const mockFeatureFlagsList = featureFlagsList as jest.MockedFunction<typeof featureFlagsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('featureFlagsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    // The list answers archived and non-archived separately. Archived flags only matter when no live flag exists.
    it.each([
        [0, 0, 'needs-setup', 2],
        [1, 0, 'has-data', 1],
        [42, 0, 'has-data', 1],
        [0, 3, 'has-data', 2],
        [1, 3, 'has-data', 1],
    ])(
        'pushes %i live and %i archived flags as status %s after %i requests',
        async (live, archived, expected, requests) => {
            mockFeatureFlagsList.mockImplementation((_projectId, params) =>
                Promise.resolve({ count: params?.archived ? archived : live, next: null, previous: null, results: [] })
            )
            const logic = featureFlagsSetupLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe(expected)
            expect(mockFeatureFlagsList).toHaveBeenCalledTimes(requests)
        }
    )

    // Undo of a project's only deleted flag reloads the flag list without remounting the gate.
    it.each([
        [0, 'needs-setup', 2],
        [1, 'has-data', 1],
    ])(
        'on a flag list reload after mounting with %i live flags (%s), makes %i requests and ends has-data',
        async (liveAtMount, statusAtMount, requests) => {
            let live = liveAtMount
            mockFeatureFlagsList.mockImplementation((_projectId, params) =>
                Promise.resolve({ count: params?.archived ? 0 : live, next: null, previous: null, results: [] })
            )
            const logic = featureFlagsSetupLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe(statusAtMount)

            live = 1
            getContext().store.dispatch(
                featureFlagsLogic.actionCreators.loadFeatureFlagsSuccess({
                    count: 1,
                    next: null,
                    previous: null,
                    results: [],
                })
            )
            await expectLogic(logic).toFinishAllListeners()
            expect(mockFeatureFlagsList).toHaveBeenCalledTimes(requests)
            expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe('has-data')
        }
    )

    it('fails open to unknown when the flag check fails before any answer', async () => {
        mockFeatureFlagsList.mockRejectedValue(new Error('network down'))
        const logic = featureFlagsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.FEATURE_FLAGS }).values.status).toBe('unknown')
    })
})
