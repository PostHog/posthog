import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { fromConditionFilterGroups, toConditionFilterGroups } from './conditionFilterGroups'

const planPro: AnyPropertyFilter = {
    key: 'plan',
    value: 'pro',
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Person,
}
const countryUs: AnyPropertyFilter = {
    key: 'country',
    value: 'US',
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Person,
}
const inCohort = { key: 'id', value: 42, type: PropertyFilterType.Cohort } as AnyPropertyFilter

const { And, Or } = FilterLogicalOperator

describe('conditionFilterGroups', () => {
    it.each([
        { case: 'a flat list', stored: [planPro, countryUs] },
        { case: 'an empty list', stored: [] },
        {
            case: 'two groups joined with OR',
            stored: {
                type: Or,
                values: [
                    { type: And, values: [planPro, countryUs] },
                    { type: And, values: [inCohort] },
                ],
            },
        },
        { case: 'one OR group', stored: { type: And, values: [{ type: Or, values: [planPro, countryUs] }] } },
    ])('saves $case back unchanged when nothing is edited', ({ stored }) => {
        const groups = toConditionFilterGroups(stored)

        expect(fromConditionFilterGroups(groups)).toEqual(stored)
    })

    it('saves one AND group as a flat list, so a condition without groups keeps its stored shape', () => {
        expect(fromConditionFilterGroups({ type: Or, values: [{ type: And, values: [planPro, countryUs] }] })).toEqual([
            planPro,
            countryUs,
        ])
    })

    it('treats a missing list as one empty group', () => {
        expect(toConditionFilterGroups(undefined)).toEqual({ type: And, values: [{ type: And, values: [] }] })
    })
})
