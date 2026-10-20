import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { keepOnlyRealtimeCohort } from './realtimeCohortStatus'

const cohort = (id: number): AnyPropertyFilter =>
    ({ key: 'id', type: PropertyFilterType.Cohort, value: id, operator: PropertyOperator.In }) as AnyPropertyFilter
const email: AnyPropertyFilter = {
    key: 'email',
    type: PropertyFilterType.Person,
    value: 'example.com',
    operator: PropertyOperator.IContains,
}

describe('keepOnlyRealtimeCohort', () => {
    it.each([
        ['condition before the cohort', [email, cohort(2)], [cohort(2)]],
        ['another cohort beside it', [cohort(3), cohort(2)], [cohort(2)]],
    ])('keeps only the realtime cohort with %s', (_name, properties, expected) => {
        expect(keepOnlyRealtimeCohort(properties, 2)).toEqual(expected)
    })

    it.each([
        // A stale preview can name a cohort the author already removed.
        ['the cohort no longer in the audience', [email, cohort(3)]],
        ['the cohort alone already', [cohort(2)]],
        ['an empty audience', []],
    ])('changes nothing, never emptying the audience, with %s', (_name, properties) => {
        expect(keepOnlyRealtimeCohort(properties, 2)).toBeNull()
    })
})
