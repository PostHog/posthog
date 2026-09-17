import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { engineeringAnalyticsSetupLogic } from './engineeringAnalyticsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('engineeringAnalyticsSetupLogic', () => {
    let sourcesSpy: jest.SpyInstance

    beforeEach(() => {
        sourcesSpy = jest.spyOn(generatedApi, 'engineeringAnalyticsSources')
        initKeaTests()
    })

    afterEach(() => {
        sourcesSpy.mockRestore()
    })

    // An unsynced source still counts: the scene explains the sync, the empty state does not.
    it.each([
        [[], 'needs-setup'],
        [[{ id: 's1', repo: 'acme/web', prefix: '', synced: false }], 'has-data'],
        [
            [
                { id: 's1', repo: 'acme/web', prefix: '', synced: true },
                { id: 's2', repo: 'acme/api', prefix: '', synced: true },
            ],
            'has-data',
        ],
    ])('pushes sources %j as status %s', async (sources, expected) => {
        sourcesSpy.mockResolvedValue(sources)
        const logic = engineeringAnalyticsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENGINEERING_ANALYTICS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the sources query fails before any answer', async () => {
        sourcesSpy.mockRejectedValue(new Error('network down'))
        const logic = engineeringAnalyticsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENGINEERING_ANALYTICS }).values.status).toBe('unknown')
    })
})
