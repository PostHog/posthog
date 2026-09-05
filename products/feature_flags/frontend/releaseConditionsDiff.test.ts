import { FeatureFlagFilters, FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { changedAspects, diffReleaseConditionSets } from './releaseConditionsDiff'

const everyone = (rollout: number | null): FeatureFlagGroupType => ({ properties: [], rollout_percentage: rollout })

const email = (
    value: string,
    rollout: number | null = 100,
    extra: Partial<FeatureFlagGroupType> = {}
): FeatureFlagGroupType => ({
    properties: [{ key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: [value] }],
    rollout_percentage: rollout,
    ...extra,
})

const cohort = (id: number, rollout: number | null = 100): FeatureFlagGroupType => ({
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: id, operator: PropertyOperator.In }],
    rollout_percentage: rollout,
})

const filters = (groups: FeatureFlagGroupType[]): FeatureFlagFilters => ({ groups, multivariate: null })

describe('diffReleaseConditionSets', () => {
    it.each([
        {
            name: 'rollout change keeps the set matched',
            before: [everyone(75)],
            after: [everyone(100)],
            statuses: ['changed'],
            aspects: [['rollout']],
            removed: [],
            reordered: false,
        },
        {
            name: 'null rollout counts as 100%',
            before: [email('a@example.com', null)],
            after: [email('a@example.com', 100)],
            statuses: ['unchanged'],
            aspects: [[]],
            removed: [],
            reordered: false,
        },
        {
            name: 'removing the first set does not mark the sets that shifted up as changed',
            before: [cohort(98), everyone(30), email('a@example.com')],
            after: [everyone(30), email('a@example.com')],
            statuses: ['unchanged', 'unchanged'],
            aspects: [[], []],
            removed: [0],
            reordered: false,
        },
        {
            name: 'a new set at the end is added',
            before: [cohort(98)],
            after: [cohort(98), email('a@example.com')],
            statuses: ['unchanged', 'added'],
            aspects: [[], []],
            removed: [],
            reordered: false,
        },
        {
            name: 'editing a value in place is a criteria change',
            before: [email('a@example.com', 50), everyone(10)],
            after: [email('b@example.com', 50), everyone(10)],
            statuses: ['changed', 'unchanged'],
            aspects: [['criteria'], []],
            removed: [],
            reordered: false,
        },
        {
            name: 'replacing a set with an unrelated one is a removal plus an addition',
            before: [cohort(98), everyone(10)],
            after: [everyone(10), email('a@example.com')],
            statuses: ['unchanged', 'added'],
            aspects: [[], []],
            removed: [0],
            reordered: false,
        },
        {
            name: 'a description-only edit is reported as a description change',
            before: [email('a@example.com', 0)],
            after: [email('a@example.com', 0, { description: 'Disabled for Example' })],
            statuses: ['changed'],
            aspects: [['description']],
            removed: [],
            reordered: false,
        },
        {
            name: 'editing a set and moving it in one save is a criteria change plus a reorder',
            before: [email('a@example.com', 50), cohort(98)],
            after: [cohort(98), email('b@example.com', 50)],
            statuses: ['unchanged', 'changed'],
            aspects: [[], ['criteria']],
            removed: [],
            reordered: true,
        },
        {
            name: 'a moved edit with two look-alike candidates stays a removal plus an addition',
            before: [email('a@example.com', 50), email('c@example.com', 50), cohort(98)],
            after: [cohort(98), cohort(411), email('b@example.com', 50)],
            statuses: ['unchanged', 'added', 'added'],
            aspects: [[], [], []],
            removed: [0, 1],
            reordered: false,
        },
        {
            name: 'swapping two sets is a reorder',
            before: [cohort(98), everyone(10)],
            after: [everyone(10), cohort(98)],
            statuses: ['unchanged', 'unchanged'],
            aspects: [[], []],
            removed: [],
            reordered: true,
        },
        {
            name: 'no before state means every set is added',
            before: undefined,
            after: [everyone(99)],
            statuses: ['added'],
            aspects: [[]],
            removed: [],
            reordered: false,
        },
    ])('$name', ({ before, after, statuses, aspects, removed, reordered }) => {
        const diff = diffReleaseConditionSets(before ? filters(before) : undefined, filters(after))

        expect(diff.sets.map((set) => set.status)).toEqual(statuses)
        expect(diff.sets.map(changedAspects)).toEqual(aspects)
        expect(diff.removed.map((set) => set.index)).toEqual(removed)
        expect(diff.reordered).toBe(reordered)
    })
})
