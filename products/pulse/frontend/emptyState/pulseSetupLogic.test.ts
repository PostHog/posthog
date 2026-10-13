import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { pulseLogic } from '../pulseLogic'
import { pulseSetupLogic } from './pulseSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('pulseSetupLogic', () => {
    let briefsSpy: jest.SpyInstance
    let configsSpy: jest.SpyInstance

    beforeEach(() => {
        briefsSpy = jest.spyOn(generatedApi, 'pulseBriefsList')
        configsSpy = jest
            .spyOn(generatedApi, 'pulseBriefConfigsList')
            .mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        initKeaTests()
    })

    afterEach(() => {
        briefsSpy.mockRestore()
        configsSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [7, 'has-data'],
    ])('pushes a brief count of %i as status %s', async (count, expected) => {
        briefsSpy.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = pulseSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PULSE }).values.status).toBe(expected)
    })

    it('re-detects when a brief is generated without leaving the scene', async () => {
        let briefCount = 0
        briefsSpy.mockImplementation(async () => ({ count: briefCount, next: null, previous: null, results: [] }))
        const logic = pulseSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PULSE }).values.status).toBe('needs-setup')

        // The empty state's run button generates the brief in place, so without the recheck
        // wiring the gate would keep hiding it until the user re-entered the scene.
        briefCount = 1
        pulseLogic.mount()
        pulseLogic.actions.generateBriefSuccess(null)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PULSE }).values.status).toBe('has-data')
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        briefsSpy.mockRejectedValue(new Error('network down'))
        const logic = pulseSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PULSE }).values.status).toBe('unknown')
    })
})
