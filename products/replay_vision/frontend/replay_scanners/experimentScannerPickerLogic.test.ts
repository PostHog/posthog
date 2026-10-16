import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { experimentScannerPickerLogic } from './experimentScannerPickerLogic'

describe('experimentScannerPickerLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/experiments/': () => [
                    200,
                    {
                        results: [
                            {
                                id: 1,
                                name: 'Checkout redesign',
                                feature_flag: { id: 10, key: 'checkout', filters: {} },
                            },
                            {
                                id: 2,
                                name: 'Org pricing page',
                                feature_flag: { id: 20, key: 'pricing', filters: { aggregation_group_type_index: 0 } },
                            },
                        ],
                    },
                ],
            },
        })
        initKeaTests()
    })

    it('leaves out experiments that aggregate by group', async () => {
        const logic = experimentScannerPickerLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadOptions()).toFinishAllListeners()

        expect(logic.values.experimentOptions.map((experiment) => experiment.id)).toEqual([1])
    })

    it('loads again on the next ensure after a failed load', async () => {
        let calls = 0
        useMocks({
            get: {
                '/api/projects/:team/experiments/': () => {
                    calls += 1
                    return calls === 1 ? [500, {}] : [200, { results: [{ id: 1, name: 'Checkout redesign' }] }]
                },
            },
        })
        const logic = experimentScannerPickerLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.ensureOptionsLoaded()).toFinishAllListeners()
        expect(logic.values.loadFailed).toBe(true)

        await expectLogic(logic, () => logic.actions.ensureOptionsLoaded()).toFinishAllListeners()
        expect(logic.values.loadFailed).toBe(false)
        expect(logic.values.experimentOptions.map((experiment) => experiment.id)).toEqual([1])
    })
})
