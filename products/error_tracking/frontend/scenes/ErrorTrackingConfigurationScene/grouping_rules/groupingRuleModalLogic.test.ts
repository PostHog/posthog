import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { ErrorTrackingGroupingRule } from '../rules/types'
import { groupingRuleModalLogic } from './groupingRuleModalLogic'

describe('groupingRuleModalLogic', () => {
    let logic: ReturnType<typeof groupingRuleModalLogic.build>

    const browserFilter: EventPropertyFilter = {
        key: '$browser',
        value: ['Firefox'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }
    const rule: ErrorTrackingGroupingRule = {
        id: 'new',
        filters: { type: FilterLogicalOperator.And, values: [browserFilter] },
        assignee: null,
        disabled_data: null,
        order_key: 0,
    }

    beforeEach(() => {
        initKeaTests()
        logic = groupingRuleModalLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        logic.unmount()
    })

    // The modal used to swallow save failures — surface the backend's validation message instead.
    it('exposes the backend validation message when a save is rejected, then clears it on edit', async () => {
        jest.spyOn(api.errorTracking, 'createRule').mockRejectedValue(
            new ApiError('Bad request', 400, undefined, { detail: 'Filters must contain at least one filter value.' })
        )

        logic.actions.openModal(rule)
        await expectLogic(logic, () => {
            logic.actions.saveRule()
        }).toFinishAllListeners()

        expect(logic.values.saveError).toBe('Filters must contain at least one filter value.')

        await expectLogic(logic, () => {
            logic.actions.updateRule(rule)
        }).toMatchValues({ saveError: null })
    })
})
