import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { engineeringAnalyticsSetupLogic } from './engineeringAnalyticsSetupLogic'

describe('engineeringAnalyticsSetupLogic', () => {
    let sourcesSpy: jest.SpyInstance
    let enableSpy: jest.SpyInstance

    beforeEach(() => {
        sourcesSpy = jest.spyOn(generatedApi, 'engineeringAnalyticsSources')
        enableSpy = jest.spyOn(generatedApi, 'engineeringAnalyticsEnable').mockResolvedValue()
        initKeaTests()
    })

    afterEach(() => {
        sourcesSpy.mockRestore()
        enableSpy.mockRestore()
    })

    // An unsynced source still counts: the scene explains the sync, the empty state does not.
    // A connected source is also the opt-in, so only that path enables the project.
    it.each([
        [[], 'needs-setup', 0],
        [[{ id: 's1', repo: 'acme/web', prefix: '', synced: false }], 'has-data', 1],
    ])('pushes sources %j as status %s and enables the project %i times', async (sources, expected, enableCalls) => {
        sourcesSpy.mockResolvedValue(sources)
        const logic = engineeringAnalyticsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENGINEERING_ANALYTICS }).values.status).toBe(expected)
        expect(enableSpy).toHaveBeenCalledTimes(enableCalls)
    })

    it('still shows the product when the viewer cannot enable it', async () => {
        sourcesSpy.mockResolvedValue([{ id: 's1', repo: 'acme/web', prefix: '', synced: true }])
        enableSpy.mockRejectedValue(new Error('403'))
        const logic = engineeringAnalyticsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ENGINEERING_ANALYTICS }).values.status).toBe('has-data')
    })
})
