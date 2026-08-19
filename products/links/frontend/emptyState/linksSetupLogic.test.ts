import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { linksSetupLogic } from './linksSetupLogic'

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('linksSetupLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(api.links, 'list')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [23, 'has-data'],
    ])('pushes a link count of %i as status %s', async (count, expected) => {
        listSpy.mockResolvedValue({ count, results: [] })
        const logic = linksSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LINKS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        listSpy.mockRejectedValue(new Error('network down'))
        const logic = linksSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LINKS }).values.status).toBe('unknown')
    })
})
