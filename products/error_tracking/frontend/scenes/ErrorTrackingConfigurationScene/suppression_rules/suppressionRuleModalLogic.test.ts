import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { ErrorTrackingSuppressionRule } from '../rules/types'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

const typeErrorFilter: EventPropertyFilter = {
    key: '$exception_types',
    value: ['TypeError'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

const persistedRule: ErrorTrackingSuppressionRule = {
    id: 'rule-id',
    filters: { type: FilterLogicalOperator.And, values: [typeErrorFilter] },
    order_key: 0,
    disabled_data: null,
    sampling_rate: 1.0,
}

describe('suppressionRuleModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.errorTracking, 'rules').mockResolvedValue({ results: [] })
        jest.spyOn(api.errorTracking, 'updateRule').mockResolvedValue()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps the modal open and shows why when the save is rejected', async () => {
        jest.spyOn(api.errorTracking, 'updateRule').mockRejectedValue(
            new ApiError('Bad Request', 400, undefined, { detail: "Invalid regular expression: '(?=Type)Error'" })
        )
        const logic = suppressionRuleModalLogic()
        logic.mount()
        logic.actions.openModal(persistedRule)

        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()

        expect(logic.values.isOpen).toBe(true)
        expect(logic.values.saveError).toBe("Invalid regular expression: '(?=Type)Error'")
        expect(logic.values.rule).toEqual(persistedRule)

        logic.unmount()
    })

    it('clears the error and closes the modal once the save succeeds', async () => {
        jest.spyOn(api.errorTracking, 'updateRule').mockRejectedValueOnce(
            new ApiError('Server Error', 500, undefined, { detail: 'A server error occurred.' })
        )
        const logic = suppressionRuleModalLogic()
        logic.mount()
        logic.actions.openModal(persistedRule)

        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()
        expect(logic.values.saveError).toBe(
            'Could not save the rule. Your changes are still here, so you can try again.'
        )

        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()
        expect(logic.values.saveError).toBeNull()
        expect(logic.values.isOpen).toBe(false)

        logic.unmount()
    })
})
