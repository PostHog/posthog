import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import type { ErrorTrackingAssignmentRule } from '../rules/types'
import { assignmentRuleModalLogic } from './assignmentRuleModalLogic'

describe('assignmentRuleModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[3, 2]] } as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('tags match count EventsQuery as error tracking', async () => {
        const browserFilter: EventPropertyFilter = {
            key: '$browser',
            value: ['Firefox'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }
        const rule: ErrorTrackingAssignmentRule = {
            id: 'new',
            filters: {
                type: FilterLogicalOperator.And,
                values: [browserFilter],
            },
            assignee: null,
            disabled_data: null,
            order_key: 0,
        }
        const logic = assignmentRuleModalLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal(rule)
            logic.actions.loadMatchCount()
        }).toFinishAllListeners()

        expect(api.query).toHaveBeenCalledWith(
            expect.objectContaining({
                tags: { productKey: ProductKey.ERROR_TRACKING },
                fixedProperties: [{ type: FilterLogicalOperator.And, values: [browserFilter] }],
            })
        )

        logic.unmount()
    })
})
