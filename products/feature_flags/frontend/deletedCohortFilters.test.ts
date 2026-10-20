import { CohortPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { deletedCohortDisabledReason } from './deletedCohortFilters'

function deletedCohort(value: number, overrides: Partial<CohortPropertyFilter> = {}): CohortPropertyFilter {
    return {
        key: 'id',
        type: PropertyFilterType.Cohort,
        operator: PropertyOperator.In,
        value,
        cohort_deleted: true,
        ...overrides,
    }
}

describe('deletedCohortDisabledReason', () => {
    it.each([
        { name: 'no condition targets a deleted cohort', filters: [], reason: undefined },
        {
            name: 'every deleted cohort can be restored',
            filters: [deletedCohort(5)],
            reason: 'A release condition targets a deleted cohort. Restore the cohort or update the release conditions first.',
        },
        {
            name: 'one deleted cohort no longer exists',
            filters: [deletedCohort(5), deletedCohort(6, { cohort_missing: true })],
            reason: 'A release condition targets a deleted cohort. Update the release conditions first.',
        },
    ])('explains the disabled control when $name', ({ filters, reason }) => {
        expect(deletedCohortDisabledReason(filters)).toBe(reason)
    })
})
