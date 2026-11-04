import {
    CohortPropertyFilter,
    FeatureFlagFilters,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { deletedCohortDisabledReason, deletedCohortFilters, withCohortAnnotationsFrom } from './deletedCohortFilters'

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

// A legacy flag can store a group whose `properties` is not a list. The flag API skips such a group.
const malformedFilters = {
    groups: [{ properties: {}, rollout_percentage: 100 }, null, { properties: [null, deletedCohort(5)] }],
} as unknown as FeatureFlagFilters

describe('deletedCohortFilters', () => {
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
            reason: 'A release condition targets a cohort that does not exist in this project. Update the release conditions first.',
        },
    ])('explains the disabled control when $name', ({ filters, reason }) => {
        expect(deletedCohortDisabledReason(filters)).toBe(reason)
    })

    it('finds the deleted cohort in a flag whose other groups are malformed', () => {
        expect(deletedCohortFilters(malformedFilters)).toEqual([deletedCohort(5)])
    })

    it('copies cohort annotations into a flag whose other groups are malformed', () => {
        const flag = { filters: malformedFilters } as FeatureFlagType
        const source = {
            filters: { groups: [{ properties: [deletedCohort(5, { cohort_name: 'Frequent buyers' })] }] },
        } as FeatureFlagType

        expect(withCohortAnnotationsFrom(flag, source).filters).toEqual({
            groups: [
                { properties: {}, rollout_percentage: 100 },
                null,
                { properties: [null, deletedCohort(5, { cohort_name: 'Frequent buyers' })] },
            ],
        })
    })
})
