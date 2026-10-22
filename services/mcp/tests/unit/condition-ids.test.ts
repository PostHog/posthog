import { describe, expect, it } from 'vitest'

import { isRecord } from '@/lib/plain-object'
import { withConditionIds } from '@/tools/featureFlags/conditionIds'
import {
    type FlagConditionGroup,
    type FlagFilters,
    preserveGroupTargetingFilters,
} from '@/tools/featureFlags/preserveGroupTargeting'

const planOn = (group_type_index: number, value: string): FlagConditionGroup => ({
    properties: [{ key: 'plan', type: 'group', group_type_index, operator: 'exact', value }],
    rollout_percentage: 100,
})

const personPlan = (value: string): FlagConditionGroup => ({
    properties: [
        { key: 'plan', type: 'person', operator: 'exact', value },
        { key: 'country', type: 'person', operator: 'exact', value: 'US' },
    ],
    rollout_percentage: 100,
})

function idOnRead(group: FlagConditionGroup, flagLevel?: number | null): unknown {
    const [read] = conditionsIn(
        withConditionIds({ filters: { groups: [group], aggregation_group_type_index: flagLevel } })
    )
    return read?.condition_id
}

function readGroups(filters: FlagFilters): FlagConditionGroup[] {
    return withConditionIds({ filters }).filters.groups ?? []
}

function echoWithId(read: FlagConditionGroup, overrides: Partial<FlagConditionGroup> = {}): FlagConditionGroup {
    return {
        condition_id: read.condition_id,
        properties: (read.properties ?? []).map(({ key, operator, value }) => ({ key, operator, value })),
        rollout_percentage: read.rollout_percentage,
        ...overrides,
    }
}

type MergeRow = {
    name: string
    flagLevel?: number
    stored: FlagConditionGroup[]
    sent: (read: FlagConditionGroup[]) => FlagConditionGroup[]
    expected: unknown[][]
}

function personAndCohortInOppositeOrders(aggregation: number | undefined): MergeRow {
    const ownAggregation = aggregation === undefined ? {} : { aggregation_group_type_index: aggregation }
    const person = { key: 'id', type: 'person', operator: 'exact', value: 'x' }
    const cohort = { key: 'id', type: 'cohort', operator: 'exact', value: 7 }
    return {
        name: `two ${aggregation === undefined ? 'person' : 'group'} sets with one ID hold a key as person and cohort in opposite orders and the agent edits one value`,
        stored: [
            { ...ownAggregation, properties: [person, cohort], rollout_percentage: 100 },
            { ...ownAggregation, properties: [cohort, person], rollout_percentage: 50 },
        ],
        sent: (stored) => [
            echoWithId(stored[0]!),
            echoWithId(stored[1]!, {
                properties: [
                    { key: 'id', operator: 'exact', value: 8 },
                    { key: 'id', operator: 'exact', value: 'x' },
                ],
            }),
        ],
        expected: [
            [aggregation ?? null, ['person', undefined], ['cohort', undefined]],
            [aggregation ?? null, [undefined, undefined], ['person', undefined]],
        ],
    }
}

function typings(filters: FlagFilters | null | undefined): unknown[][] {
    return (filters?.groups ?? []).map((group) => [
        group.aggregation_group_type_index ?? null,
        ...(group.properties ?? []).map((prop) => [prop.type, prop.group_type_index]),
    ])
}

const flag = (id: number): Record<string, unknown> => ({
    id,
    key: `flag-${id}`,
    filters: {
        groups: [{ ...planOn(0, `plan-${id}`), aggregation_group_type_index: 0 }, personPlan('free')],
        multivariate: null,
    },
    active: true,
})

const experiment = (id: number): Record<string, unknown> => ({
    id,
    name: `Experiment ${id}`,
    feature_flag_key: `flag-${id + 100}`,
    feature_flag: flag(id + 100),
    metrics: [],
    status: 'running',
})

function conditionsIn(value: unknown): Record<string, unknown>[] {
    if (Array.isArray(value)) {
        return value.flatMap(conditionsIn)
    }
    if (!isRecord(value)) {
        return []
    }
    return Object.entries(value).flatMap(([key, nested]) =>
        key === 'filters' && isRecord(nested) && Array.isArray(nested.groups)
            ? nested.groups.filter(isRecord)
            : conditionsIn(nested)
    )
}

function withoutConditionIds(value: unknown): unknown {
    return JSON.parse(JSON.stringify(value, (key, nested) => (key === 'condition_id' ? undefined : nested)))
}

describe('condition ids', () => {
    it('gives the same ID to one stored condition however the API renders it', () => {
        const stored = {
            aggregation_group_type_index: null,
            properties: [
                { key: 'id', type: 'cohort', operator: 'in', value: 7 },
                { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'pro' },
                { key: '$group_key', type: 'group', group_type_index: 0, operator: 'exact', value: 'acme' },
            ],
            rollout_percentage: 50,
        }
        const rendered = {
            ...stored,
            properties: [
                { ...stored.properties[1]! },
                { ...stored.properties[0]!, cohort_name: 'Paying customers' },
                { ...stored.properties[2]!, group_key_names: { acme: 'Acme Inc' } },
            ],
            rollout_percentage: 75,
            variant: 'test',
            description: 'Edited in the UI',
            sort_key: 'abc-123',
        }

        expect(idOnRead(rendered)).toBe(idOnRead(stored))
    })

    it.each([
        { name: 'key', change: { key: 'tier' } },
        { name: 'type', change: { type: 'person' } },
        { name: 'group_type_index', change: { group_type_index: 1 } },
        { name: 'value', change: { value: 'enterprise' } },
        { name: 'operator', change: { operator: 'icontains' } },
    ])('gives a condition a new ID when a property changes its $name', ({ change }) => {
        const stored = planOn(0, 'pro')
        const changed = { ...stored, properties: [{ ...stored.properties![0]!, ...change }] }

        expect(idOnRead(changed)).not.toBe(idOnRead(stored))
    })

    it.each([
        { name: 'a group type', flagLevel: 0 },
        { name: 'persons', flagLevel: null },
    ])(
        'keeps the ID of a condition without an aggregation when the API writes a flag level of $name into it',
        ({ flagLevel }) => {
            const absent = planOn(0, 'pro')

            expect(idOnRead({ ...absent, aggregation_group_type_index: flagLevel }, flagLevel)).toBe(
                idOnRead(absent, flagLevel)
            )
        }
    )

    it('tells an explicit null aggregation from an absent one on a flag that aggregates on a group type', () => {
        const absent = planOn(0, 'pro')

        expect(idOnRead({ ...absent, aggregation_group_type_index: null }, 0)).not.toBe(idOnRead(absent, 0))
    })

    it.each([
        { name: 'a flag', value: flag(9) },
        { name: 'an experiment', value: experiment(5) },
        {
            name: 'a page of experiments where one has no flag',
            value: {
                count: 2,
                next: 'https://us.posthog.com/api/projects/42/experiments/?offset=2',
                results: [experiment(5), { ...experiment(6), feature_flag: null }],
                _posthogUrl: 'https://us.posthog.com/project/42/experiments',
            },
        },
        {
            name: 'a list of my-flags rows',
            value: [
                { feature_flag: flag(9), value: true },
                { feature_flag: flag(10), value: 'test' },
            ],
        },
        { name: 'a lookup miss', value: { found: false, key: 'flag-9', message: 'No feature flag' } },
        {
            name: 'a flag whose conditions carry a saved condition_id',
            value: { id: 9, filters: { groups: [{ condition_id: 'saved-by-api', ...personPlan('free') }] } },
        },
    ])('adds an ID to each condition of $name and changes nothing else', ({ value }) => {
        const result = withConditionIds(structuredClone(value))

        expect(conditionsIn(result).map((group) => group.condition_id)).toEqual(
            conditionsIn(withoutConditionIds(value)).map((group) => idOnRead(group))
        )
        expect(withoutConditionIds(result)).toEqual(withoutConditionIds(value))
    })

    it.each<MergeRow>([
        {
            name: 'two person sets on different group types trade places',
            stored: [planOn(0, 'enterprise'), planOn(1, 'pro')],
            sent: (stored) => [echoWithId(stored[1]!), echoWithId(stored[0]!)],
            expected: [
                [null, ['group', 1]],
                [null, ['group', 0]],
            ],
        },
        {
            name: 'the first of two person sets is deleted',
            stored: [planOn(0, 'pro'), planOn(1, 'pro')],
            sent: (stored) => [echoWithId(stored[1]!)],
            expected: [[null, ['group', 1]]],
        },
        {
            name: 'a set moves and changes its value',
            stored: [planOn(0, 'enterprise'), planOn(1, 'pro')],
            sent: (stored) => [
                echoWithId(stored[1]!, {
                    properties: [{ key: 'plan', operator: 'exact', value: 'business' }],
                }),
                echoWithId(stored[0]!),
            ],
            expected: [
                [null, ['group', 1]],
                [null, ['group', 0]],
            ],
        },
        {
            name: 'two sets with different keys trade places',
            stored: [planOn(0, 'enterprise'), personPlan('free')],
            sent: (stored) => [echoWithId(stored[1]!), echoWithId(stored[0]!)],
            expected: [
                [null, ['person', undefined], ['person', undefined]],
                [null, ['group', 0]],
            ],
        },
        {
            name: 'a person set and a group set on a mixed flag trade places',
            stored: [
                { ...personPlan('free'), aggregation_group_type_index: null },
                { ...planOn(0, 'enterprise'), aggregation_group_type_index: 0 },
            ],
            sent: (stored) => [echoWithId(stored[1]!), echoWithId(stored[0]!)],
            expected: [
                [0, ['group', 0]],
                [null, ['person', undefined], ['person', undefined]],
            ],
        },
        {
            name: 'the agent copies a condition and edits the copy',
            stored: [planOn(0, 'enterprise'), planOn(1, 'pro')],
            sent: (stored) => [
                echoWithId(stored[1]!),
                echoWithId(stored[1]!, { properties: [{ key: 'plan', operator: 'exact', value: 'business' }] }),
                echoWithId(stored[0]!),
            ],
            expected: [
                [null, ['group', 1]],
                [null, ['group', 1]],
                [null, ['group', 0]],
            ],
        },
        {
            name: 'a new set without an ID repeats a key that a stored person set holds as a group property',
            stored: [planOn(0, 'enterprise')],
            sent: (stored) => [
                echoWithId(stored[0]!),
                { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
            ],
            expected: [
                [null, ['group', 0]],
                [null, [undefined, undefined]],
            ],
        },
        ...[undefined, 0].map(personAndCohortInOppositeOrders),
        {
            name: 'a kept condition gains a key that another stored set holds as a group property',
            stored: [
                personPlan('free'),
                {
                    properties: [{ key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' }],
                    rollout_percentage: 100,
                },
            ],
            sent: (stored) => [
                echoWithId(stored[0]!, {
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'free' },
                        { key: 'country', operator: 'exact', value: 'US' },
                        { key: 'region', operator: 'exact', value: 'eu' },
                    ],
                }),
                echoWithId(stored[1]!),
            ],
            expected: [
                [null, ['person', undefined], ['person', undefined], [undefined, undefined]],
                [null, ['group', 1]],
            ],
        },
        {
            name: 'a kept group set gains a key that a stored person set holds as a person property',
            stored: [
                { ...planOn(0, 'enterprise'), aggregation_group_type_index: 0 },
                { ...personPlan('free'), aggregation_group_type_index: null },
            ],
            sent: (stored) => [
                echoWithId(stored[0]!, {
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'enterprise' },
                        { key: 'country', operator: 'exact', value: 'US' },
                    ],
                }),
                echoWithId(stored[1]!),
            ],
            expected: [
                [0, ['group', 0], ['person', undefined]],
                [null, ['person', undefined], ['person', undefined]],
            ],
        },
        {
            name: 'a new set without an ID goes in front of the stored sets',
            stored: [planOn(0, 'enterprise'), planOn(1, 'pro')],
            sent: (stored) => [
                { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
                echoWithId(stored[0]!),
                echoWithId(stored[1]!),
            ],
            expected: [
                [null, [undefined, undefined]],
                [null, ['group', 0]],
                [null, ['group', 1]],
            ],
        },
        {
            name: 'two group sets that take the flag level trade places',
            flagLevel: 0,
            stored: [planOn(0, 'enterprise'), planOn(0, 'pro')],
            sent: (stored) => [echoWithId(stored[1]!), echoWithId(stored[0]!)],
            expected: [
                [null, ['group', 0]],
                [null, ['group', 0]],
            ],
        },
    ])(
        'restores each condition from the stored condition with its ID when $name',
        ({ flagLevel, stored, sent, expected }) => {
            const existing = { groups: stored, aggregation_group_type_index: flagLevel }
            const merged = preserveGroupTargetingFilters(existing, { groups: sent(readGroups(existing)) })

            expect(typings(merged)).toEqual(expected)
            expect(merged?.groups?.every((group) => !('condition_id' in group))).toBe(true)
        }
    )

    it('types a key the source does not hold from every stored set when the update retargets a mixed flag', () => {
        const mixed = [
            { ...planOn(0, 'enterprise'), aggregation_group_type_index: 0 },
            { ...personPlan('free'), aggregation_group_type_index: null },
        ]
        const [groupSet, personSet] = readGroups({ groups: mixed })

        const merged = preserveGroupTargetingFilters(
            { groups: mixed },
            {
                aggregation_group_type_index: 1,
                groups: [
                    echoWithId(groupSet!, {
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'enterprise' },
                            { key: 'country', operator: 'exact', value: 'US' },
                        ],
                    }),
                    echoWithId(personSet!),
                ],
            }
        )

        expect(typings(merged)).toEqual([
            [null, ['group', 1], ['person', undefined]],
            [null, ['person', undefined], ['person', undefined]],
        ])
    })

    it('refuses a condition ID that matches no stored condition', () => {
        const stored = [planOn(0, 'enterprise'), planOn(1, 'pro')]
        const [kept] = readGroups({ groups: stored })
        const [fromAnotherFlag] = readGroups({ groups: [planOn(2, 'pro')] })

        expect(() =>
            preserveGroupTargetingFilters(
                { groups: stored },
                { groups: [echoWithId(kept!), echoWithId(fromAnotherFlag!)] }
            )
        ).toThrow(
            expect.objectContaining({
                fields: ['filters.groups.N.condition_id:stale_condition_id'],
                message: expect.stringMatching(
                    /on filters\.groups\[1\] matches no condition.*copied this condition from another flag .* remove its condition_id/
                ),
            })
        )
    })

    it('refuses a new condition in front of the stored ones on a mixed flag when it states no aggregation', () => {
        const mixed = [
            { ...personPlan('free'), aggregation_group_type_index: null },
            { ...planOn(0, 'enterprise'), aggregation_group_type_index: 0 },
        ]

        expect(() =>
            preserveGroupTargetingFilters(
                { groups: mixed },
                {
                    groups: [
                        { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                        ...readGroups({ groups: mixed }).map((read) => echoWithId(read)),
                    ],
                }
            )
        ).toThrow(/conditions: filters\.groups\[0\]\. /)
    })
})
