import { describe, expect, it } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import {
    type FlagConditionGroup,
    type FlagFilters,
    type FlagProperty,
    preserveGroupTargetingFilters,
} from '@/tools/featureFlags/preserveGroupTargeting'

const PERSON_AGGREGATED_PROPERTY_TYPES = ['person', 'cohort', 'flag']

function setAggregation(group: FlagConditionGroup, flagLevel: number | null | undefined): number | null | undefined {
    return 'aggregation_group_type_index' in group ? group.aggregation_group_type_index : flagLevel
}

function isGroupPropertyOfStoredPersonSet(existing: FlagFilters, groupIndex: number, property: FlagProperty): boolean {
    const stored = existing.groups?.[groupIndex]
    if (!stored) {
        return false
    }
    const storedAggregation = setAggregation(stored, existing.aggregation_group_type_index)
    return (
        (storedAggregation === undefined || storedAggregation === null) &&
        property.type === 'group' &&
        !!stored.properties?.some(
            (candidate) =>
                candidate.key === property.key &&
                candidate.type === 'group' &&
                candidate.group_type_index === property.group_type_index
        )
    )
}

/**
 * Mirrors check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py, over the state that validator sees:
 * the flag level the backend keeps when the payload omits it, then each set's own key. This helper
 * skips a property with no type, which the backend rule reports. A test asserts the fields of a
 * property left untyped instead.
 *
 * The backend rule also reports a group property in a person-aggregated set. The flag evaluator
 * supports that shape. This helper accepts it only where the stored set at the same index already
 * held it: that set aggregates on persons and holds the key as a group property on the same group
 * type. A group property that the merge adds to a person-aggregated set still counts as a violation.
 */
function aggregationViolations(existing: FlagFilters, merged: FlagFilters | null | undefined): string[] {
    const violations: string[] = []
    const flagLevel =
        merged && 'aggregation_group_type_index' in merged
            ? merged.aggregation_group_type_index
            : existing.aggregation_group_type_index
    for (const [groupIndex, group] of (merged?.groups ?? []).entries()) {
        const aggregation = setAggregation(group, flagLevel)
        for (const [propertyIndex, property] of (group.properties ?? []).entries()) {
            const path = `groups[${groupIndex}].properties[${propertyIndex}]`
            if (typeof property.type !== 'string') {
                continue
            }
            if (aggregation === undefined || aggregation === null) {
                if (
                    !PERSON_AGGREGATED_PROPERTY_TYPES.includes(property.type) &&
                    !isGroupPropertyOfStoredPersonSet(existing, groupIndex, property)
                ) {
                    violations.push(`${path}: person_aggregation_property_type`)
                }
            } else if (property.type !== 'group') {
                violations.push(`${path}: group_aggregation_property_type`)
            } else if (property.group_type_index !== aggregation) {
                violations.push(`${path}: group_property_type_index_mismatch`)
            }
        }
    }
    return violations
}

/** The condition set paths a refusal names, or none when the merge goes through. */
function refusedSets(merge: () => unknown): string[] {
    try {
        merge()
    } catch (error) {
        if (error instanceof ToolInputValidationError) {
            expect(error.fields).toEqual(['filters.groups.N.aggregation_group_type_index:unresolved_aggregation'])
            return [...error.message.matchAll(/filters\.groups\[\d+\]/g)].map((match) => match[0])
        }
        throw error
    }
    return []
}

describe('preserveGroupTargetingFilters', () => {
    const existingGroupFlag = {
        aggregation_group_type_index: 0,
        groups: [
            {
                aggregation_group_type_index: 0,
                properties: [
                    {
                        key: 'plan',
                        type: 'group',
                        group_type_index: 0,
                        operator: 'exact',
                        value: 'enterprise',
                    },
                ],
                rollout_percentage: 100,
            },
        ],
    }

    const existingMixedFlag = {
        aggregation_group_type_index: null,
        groups: [
            {
                aggregation_group_type_index: 0,
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                ],
                rollout_percentage: 100,
            },
            {
                aggregation_group_type_index: null,
                properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                rollout_percentage: 100,
            },
        ],
    }

    const existingTwoGroupTypeFlag = {
        groups: [
            {
                aggregation_group_type_index: 0,
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                ],
                rollout_percentage: 100,
            },
            {
                aggregation_group_type_index: 1,
                properties: [{ key: 'name', type: 'group', group_type_index: 1, operator: 'exact', value: 'acme' }],
                rollout_percentage: 100,
            },
        ],
    }

    const existingSameKeyMixedFlag = {
        aggregation_group_type_index: null,
        groups: [
            {
                aggregation_group_type_index: null,
                properties: [{ key: 'plan', type: 'person', operator: 'exact', value: 'free' }],
                rollout_percentage: 100,
            },
            {
                aggregation_group_type_index: 0,
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                ],
                rollout_percentage: 100,
            },
        ],
    }

    const existingPersonThenTwoGroupTypesFlag = {
        aggregation_group_type_index: null,
        groups: [
            {
                aggregation_group_type_index: null,
                properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                rollout_percentage: 100,
            },
            {
                aggregation_group_type_index: 0,
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                ],
                rollout_percentage: 100,
            },
            {
                aggregation_group_type_index: 1,
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                    { key: 'seats', type: 'group', group_type_index: 1, operator: 'gt', value: 10 },
                ],
                rollout_percentage: 100,
            },
        ],
    }

    const existingPersonSetWithGroupPropertyFlag = {
        groups: [
            {
                properties: [
                    { key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' },
                    { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                ],
                rollout_percentage: 100,
            },
        ],
    }

    const existingGroupAndPersonPlanSetsFlag = {
        groups: [
            {
                properties: [
                    { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                ],
                rollout_percentage: 100,
            },
            {
                properties: [
                    { key: 'plan', type: 'person', operator: 'exact', value: 'free' },
                    { key: 'country', type: 'person', operator: 'exact', value: 'US' },
                ],
                rollout_percentage: 100,
            },
        ],
    }

    it('preserves aggregation_group_type_index when omitted on update', () => {
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                    rollout_percentage: 50,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        expect(merged?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.value).toBe('pro')
        expect(merged?.groups?.[0]?.rollout_percentage).toBe(50)
        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
    })

    it('does not override explicit person type and pins set to person aggregation', () => {
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        // The set must not carry group aggregation around a person property.
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('person')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBeUndefined()
        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBeNull()
    })

    // The agent moves a set that aggregates on group type 0 to persons. The stored group property
    // filtered on that group type. A key that matches it must not resurrect it.
    it.each([
        { name: 'a key with no existing match', key: 'email', operator: 'icontains', value: '@acme.com' },
        { name: 'a key matching an existing group property', key: 'plan', operator: 'exact', value: 'pro' },
    ])('honors explicit null aggregation_group_type_index for $name', ({ key, operator, value }) => {
        const incoming = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: null,
                    properties: [{ key, operator, value }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        expect(merged?.aggregation_group_type_index).toBeNull()
        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBeNull()
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBeUndefined()
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBeUndefined()
    })

    // A mixed-aggregation flag is stored with a null flag level and per-set indices, and
    // the tool tells agents to echo that back. The null must not pin a set sending its own index.
    it('keeps group targeting on a set carrying its own index when the flag level is null', () => {
        const merged = preserveGroupTargetingFilters(existingMixedFlag, {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.properties?.[0]?.type).toBe('person')
    })

    it('pins a set that omits the aggregation key when only the flag level is nulled', () => {
        const merged = preserveGroupTargetingFilters(existingGroupFlag, {
            aggregation_group_type_index: null,
            groups: [{ properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 }],
        })

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBeUndefined()
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBeUndefined()
    })

    it('restores each condition set aggregation from the existing set at the same index', () => {
        const merged = preserveGroupTargetingFilters(existingTwoGroupTypeFlag, {
            groups: [
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                { properties: [{ key: 'name', operator: 'exact', value: 'globex' }], rollout_percentage: 100 },
            ],
        })

        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBe(1)
        expect(merged?.groups?.[1]?.properties?.[0]?.group_type_index).toBe(1)
    })

    it('fills group_type_index when the agent sets type "group" but omits the index', () => {
        const merged = preserveGroupTargetingFilters(existingGroupFlag, {
            groups: [
                {
                    properties: [{ key: 'plan', type: 'group', operator: 'exact', value: 'pro' }],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
    })

    it('does not group-infer an untyped property in a set that also holds an explicit person property', () => {
        const incoming = {
            groups: [
                {
                    properties: [
                        { key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' },
                        { key: 'plan', operator: 'exact', value: 'pro' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBeNull()
        expect(merged?.groups?.[0]?.properties?.[1]?.type).toBeUndefined()
        expect(merged?.groups?.[0]?.properties?.[1]?.group_type_index).toBeUndefined()
    })

    // `person_metadata` guards the restore against a hardcoded type list. Rust accepts that type
    // and FEATURE_FLAG_PROPERTY_TYPES does not list it, so a list copied from the backend drops it.
    it.each([
        { type: 'person', key: 'email', operator: 'icontains', value: '@acme.com' },
        { type: 'cohort', key: 'id', operator: 'in', value: 42 },
        { type: 'flag', key: 'other-flag', operator: 'flag_evaluates_to', value: true },
        { type: 'person_metadata', key: 'created_at', operator: 'is_date_after', value: '2026-01-01' },
    ])(
        'still restores a $type property type in a set pinned to person aggregation',
        ({ type, key, operator, value }) => {
            const existingPersonSetFlag = {
                aggregation_group_type_index: 0,
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key, type, operator, value }],
                        rollout_percentage: 100,
                    },
                ],
            }
            const incoming = {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key, operator, value }],
                        rollout_percentage: 100,
                    },
                ],
            }

            const merged = preserveGroupTargetingFilters(existingPersonSetFlag, incoming)

            expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe(type)
        }
    )

    it('keeps explicit group type and index from the agent', () => {
        const incoming = {
            aggregation_group_type_index: 1,
            groups: [
                {
                    properties: [
                        {
                            key: 'region',
                            type: 'group',
                            group_type_index: 1,
                            operator: 'exact',
                            value: 'eu',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        expect(merged?.aggregation_group_type_index).toBe(1)
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(1)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(aggregationViolations(existingGroupFlag, merged)).toEqual([])
    })

    it('infers type group from flag-level aggregation when property type omitted', () => {
        const existing = { aggregation_group_type_index: 2, groups: [{ properties: [], rollout_percentage: 100 }] }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'tier', operator: 'exact', value: 'gold' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.aggregation_group_type_index).toBe(2)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(2)
    })

    it('passes through when there is no existing flag', () => {
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'email', operator: 'exact', value: 'a@b.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(undefined, incoming)

        expect(merged?.aggregation_group_type_index).toBeUndefined()
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBeUndefined()
    })

    // Collapsing two sets into one leaves every set without a source. The flag level decides the type.
    it('types a collapsed set from the flag-level aggregation', () => {
        const existing = {
            aggregation_group_type_index: 0,
            groups: [
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@corp.com' }],
                    rollout_percentage: 100,
                },
                {
                    properties: [
                        {
                            key: 'plan',
                            type: 'group',
                            group_type_index: 0,
                            operator: 'exact',
                            value: 'enterprise',
                        },
                    ],
                    rollout_percentage: 50,
                },
            ],
        }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                    rollout_percentage: 75,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.value).toBe('pro')
    })

    // The source holds the key as both a person and a group property, so the stored type is
    // ambiguous. The set's group type then decides the property type, whichever operator the agent sends.
    it('restores group type and index for a duplicate key', () => {
        const existing = {
            aggregation_group_type_index: 0,
            groups: [
                {
                    properties: [
                        { key: 'name', type: 'person', operator: 'icontains', value: 'acme' },
                        {
                            key: 'name',
                            type: 'group',
                            group_type_index: 0,
                            operator: 'exact',
                            value: 'Acme Corp',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'name', operator: 'regex', value: '.*' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.value).toBe('.*')
    })

    const personAndCohortCandidates = [
        { key: 'name', type: 'person', operator: 'icontains', value: 'acme' },
        { key: 'name', type: 'cohort', operator: 'in', value: 42 },
    ]
    const groupAndPersonCandidates = [
        { key: 'name', type: 'group', group_type_index: 0, operator: 'icontains', value: 'acme' },
        { key: 'name', type: 'person', operator: 'exact', value: 'acme' },
    ]

    // The candidates decide the type when the set aggregates on person, or on a group with no
    // group candidate for the key. The operator picks between two candidates that share a key,
    // and the value picks between those. When the remaining candidates hold more than one type,
    // the property stays untyped.
    it.each([
        { name: 'the operator matches the cohort candidate', operator: 'in', expected: { type: 'cohort' } },
        { name: 'the operator matches the person candidate', operator: 'icontains', expected: { type: 'person' } },
        { name: 'the operator matches neither candidate', operator: 'regex', expected: {} },
        {
            name: 'the operator matches neither candidate in a group-aggregated set',
            aggregation: 0,
            operator: 'regex',
            expected: {},
        },
        {
            name: 'the operator matches a group candidate',
            stored: groupAndPersonCandidates,
            operator: 'icontains',
            expected: { type: 'group', group_type_index: 0 },
        },
        {
            name: 'the operator matches a person candidate next to a group candidate',
            stored: groupAndPersonCandidates,
            operator: 'exact',
            expected: { type: 'person' },
        },
        {
            name: 'the value matches one of two group candidates with the same operator',
            stored: [
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 1, operator: 'exact', value: 'globex' },
            ],
            operator: 'exact',
            value: 'globex',
            expected: { type: 'group', group_type_index: 1 },
        },
        {
            name: 'the value matches neither a person nor a group candidate with the same operator',
            stored: [
                { key: 'name', type: 'person', operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'globex' },
            ],
            operator: 'exact',
            value: 'initech',
            expected: {},
        },
        {
            name: 'the value matches neither a person nor a cohort candidate with the same operator',
            stored: [
                { key: 'name', type: 'person', operator: 'exact', value: 'acme' },
                { key: 'name', type: 'cohort', operator: 'exact', value: 42 },
            ],
            operator: 'exact',
            value: 43,
            expected: {},
        },
        {
            name: 'a person and a group candidate both match the operator and value',
            stored: [
                { key: 'name', type: 'person', operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'acme' },
            ],
            operator: 'exact',
            expected: {},
        },
        {
            name: 'two person candidates differ only in a numeric group_type_index',
            stored: [
                { key: 'name', type: 'person', group_type_index: 0, operator: 'exact', value: 'acme' },
                { key: 'name', type: 'person', operator: 'icontains', value: 'acme' },
            ],
            operator: 'regex',
            expected: { type: 'person' },
        },
        {
            name: 'the edit omits the operator and a person candidate uses exact',
            stored: groupAndPersonCandidates,
            operator: undefined,
            value: 'pro',
            expected: { type: 'person' },
        },
        {
            name: 'a person candidate omits the operator and the edit uses exact',
            stored: [
                { key: 'name', type: 'group', group_type_index: 0, operator: 'icontains', value: 'acme' },
                { key: 'name', type: 'person', value: 'acme' },
            ],
            operator: 'exact',
            value: 'pro',
            expected: { type: 'person' },
        },
        {
            name: 'two group candidates on different group types match neither the value nor a sent index',
            stored: [
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 1, operator: 'exact', value: 'globex' },
            ],
            operator: 'exact',
            value: 'initech',
            expected: {},
        },
        {
            name: 'the edit sends a group index and a person and a group candidate disagree on type',
            stored: [
                { key: 'name', type: 'person', operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'globex' },
            ],
            operator: 'exact',
            value: 'initech',
            index: 0,
            expected: { group_type_index: 0 },
        },
        {
            name: 'the edit sends a group index and two group candidates differ only in index',
            stored: [
                { key: 'name', type: 'group', group_type_index: 0, operator: 'exact', value: 'acme' },
                { key: 'name', type: 'group', group_type_index: 1, operator: 'exact', value: 'globex' },
            ],
            operator: 'exact',
            value: 'initech',
            index: 1,
            expected: { type: 'group', group_type_index: 1 },
        },
    ])(
        'chooses a duplicate-key type, or none, by operator and value when $name',
        ({ stored = personAndCohortCandidates, aggregation, operator, value = 'acme', index, expected }) => {
            const existing = {
                ...(aggregation === undefined ? {} : { aggregation_group_type_index: aggregation }),
                groups: [{ properties: stored, rollout_percentage: 100 }],
            }
            const incoming = {
                groups: [
                    {
                        properties: [{ key: 'name', operator, value, group_type_index: index }],
                        rollout_percentage: 100,
                    },
                ],
            }

            const merged = preserveGroupTargetingFilters(existing, incoming)

            expect(merged?.groups?.[0]?.properties?.[0]).toEqual({ key: 'name', operator, value, ...expected })
            expect(aggregationViolations(existing, merged)).toEqual([])
        }
    )

    it('does not copy set-level aggregation onto a newly appended condition set', () => {
        const existing = {
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        {
                            key: 'plan',
                            type: 'group',
                            group_type_index: 0,
                            operator: 'exact',
                            value: 'enterprise',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }
        const incoming = {
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        {
                            key: 'plan',
                            type: 'group',
                            group_type_index: 0,
                            operator: 'exact',
                            value: 'enterprise',
                        },
                    ],
                    rollout_percentage: 100,
                },
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBeNull()
        expect(merged?.groups?.[1]?.properties?.[0]?.type).toBe('person')
    })

    // The flag evaluator reads each property by its own type and group_type_index. A
    // person-aggregated set can therefore filter on a group property. No set or flag level in this
    // flag carries a group index. The restored index can only come from the stored property.
    it.each([
        { name: 'the set omits its aggregation' },
        { name: 'the payload sends a null flag level', flag: { aggregation_group_type_index: null } },
        { name: 'the set carries an explicit person property', email: { type: 'person' } },
        {
            name: 'the agent echoes the property with its group type and index',
            region: { type: 'group', group_type_index: 1 },
        },
        {
            name: 'a changed key leaves the set with no source and the agent echoes the group property',
            email: { key: 'country' },
            region: { type: 'group', group_type_index: 1 },
        },
    ])(
        'keeps a stored group property in a person-aggregated set when $name',
        ({ flag = {}, email = {}, region = {} }) => {
            const existing = existingPersonSetWithGroupPropertyFlag

            const merged = preserveGroupTargetingFilters(existing, {
                ...flag,
                groups: [
                    {
                        properties: [
                            { key: 'email', operator: 'icontains', value: '@acme.com', ...email },
                            { key: 'region', operator: 'exact', value: 'eu', ...region },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            })

            expect(merged?.groups?.[0]?.properties?.[1]).toEqual({
                key: 'region',
                type: 'group',
                group_type_index: 1,
                operator: 'exact',
                value: 'eu',
            })
            expect(merged?.groups?.[0]?.aggregation_group_type_index ?? null).toBeNull()
            expect(aggregationViolations(existing, merged)).toEqual([])
        }
    )

    // The backend rule reports this payload. This test therefore skips the oracle that copies the rule.
    it('keeps a person-aggregated set when an echoed group property disagrees with a moved one', () => {
        const existing = {
            groups: [
                {
                    properties: [
                        { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                        { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    properties: [
                        { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'pro' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index ?? null).toBeNull()
        expect(merged?.groups?.[0]?.properties?.map((prop) => prop.group_type_index)).toEqual([1, 0])
    })

    // The oracle needs a stored set at the same index to accept a group property. An appended set has none.
    it('keeps an appended set on persons when it repeats a group property that a stored set holds', () => {
        const existing = existingPersonSetWithGroupPropertyFlag

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                ...existing.groups,
                {
                    properties: [{ key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'eu' }],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties).toEqual(existing.groups[0]?.properties)
        expect(merged?.groups?.[0]?.aggregation_group_type_index ?? null).toBeNull()
        expect(merged?.groups?.[1]?.properties?.[0]).toEqual({
            key: 'region',
            type: 'group',
            group_type_index: 1,
            operator: 'exact',
            value: 'eu',
        })
        expect(merged?.groups?.[1]?.aggregation_group_type_index ?? null).toBeNull()
    })

    it('moves a person set to group aggregation when no single stored set holds every typed group property', () => {
        const otherSet = {
            properties: [
                { key: 'plan', type: 'person', operator: 'exact', value: 'free' },
                { key: 'country', type: 'group', group_type_index: 0, operator: 'exact', value: 'CA' },
            ],
            rollout_percentage: 50,
        }
        const existing = {
            groups: [
                {
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'business' },
                        { key: 'country', type: 'person', operator: 'exact', value: 'US' },
                    ],
                    rollout_percentage: 50,
                },
                otherSet,
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'free' },
                        { key: 'country', type: 'group', group_type_index: 0, operator: 'exact', value: 'CA' },
                    ],
                    rollout_percentage: 50,
                },
                otherSet,
            ],
        })

        expect(merged?.groups?.map((group) => group.aggregation_group_type_index ?? null)).toEqual([0, null])
    })

    const onGroupType0 = { type: 'group', group_type_index: 0 }
    const onGroupType1 = { type: 'group', group_type_index: 1 }
    const planOnTwoGroupTypes = [
        { ...onGroupType0, value: 'enterprise' },
        { ...onGroupType1, value: 'pro' },
    ]

    it.each([
        { name: 'the sets trade places', values: ['pro', 'enterprise'], restored: [{}, {}] },
        {
            name: 'the sets trade places and the agent omits the operator',
            values: ['pro', 'enterprise'],
            typed: [{ operator: undefined }, { operator: undefined }],
            restored: [{ operator: undefined }, { operator: undefined }],
        },
        { name: 'a set changes to a new value', values: ['business', 'pro'], restored: [onGroupType0, onGroupType1] },
        { name: 'a set copies the value of the other set', values: ['pro', 'pro'], restored: [{}, onGroupType1] },
        {
            name: 'the agent echoes two sets that share a value',
            stored: [
                { ...onGroupType0, value: 'enterprise' },
                { ...onGroupType1, value: 'enterprise' },
            ],
            values: ['enterprise', 'enterprise'],
            restored: [onGroupType0, onGroupType1],
        },
        {
            name: 'both sets filter on one group type and trade places',
            stored: [
                { ...onGroupType0, value: 'enterprise' },
                { ...onGroupType0, value: 'pro' },
            ],
            values: ['pro', 'enterprise'],
            restored: [onGroupType0, onGroupType0],
        },
        {
            name: 'the sets trade places and a third set holds the key as a person property',
            stored: [...planOnTwoGroupTypes, { type: 'person', value: 'free' }],
            values: ['pro', 'enterprise', 'free'],
            restored: [{}, {}, { type: 'person' }],
        },
        {
            name: 'a group property and a person property on one key trade places',
            stored: [
                { ...onGroupType0, value: 'enterprise' },
                { type: 'person', value: 'free' },
            ],
            values: ['free', 'enterprise'],
            restored: [{}, {}],
        },
        {
            name: 'two other sets hold the moved value on different group types',
            stored: [
                { ...onGroupType0, value: 'enterprise' },
                { ...onGroupType0, value: 'pro' },
                { ...onGroupType1, value: 'pro' },
            ],
            values: ['pro', 'enterprise', 'pro'],
            restored: [{}, onGroupType0, {}],
        },
        {
            name: 'two sets with one filter on different group types trade rollouts',
            stored: [
                { ...onGroupType0, value: 'business' },
                { ...onGroupType1, value: 'business' },
            ],
            storedRollouts: [100, 0],
            values: ['business', 'business'],
            sentRollouts: [0, 100],
            restored: [{}, {}],
        },
        {
            name: 'two sets with one filter on different group types trade variants',
            stored: [
                { ...onGroupType0, value: 'business' },
                { ...onGroupType1, value: 'business' },
            ],
            storedVariants: ['control', 'test'],
            values: ['business', 'business'],
            sentVariants: ['test', 'control'],
            restored: [{}, {}],
        },
        {
            name: 'a set changes only its rollout',
            values: ['enterprise', 'pro'],
            sentRollouts: [50, 100],
            restored: [onGroupType0, onGroupType1],
        },
        {
            name: 'the agent deletes one of two sets that differ only in property type',
            stored: [
                { ...onGroupType1, value: 'pro' },
                { type: 'person', value: 'pro' },
            ],
            values: ['pro'],
            restored: [{}],
        },
        {
            name: 'the agent echoes two sets that differ only in property type',
            stored: [
                { ...onGroupType1, value: 'pro' },
                { type: 'person', value: 'pro' },
            ],
            values: ['pro', 'pro'],
            restored: [onGroupType1, { type: 'person' }],
        },
        {
            name: 'the agent types both properties after the sets trade places',
            values: ['pro', 'enterprise'],
            typed: [onGroupType1, onGroupType0],
            restored: [onGroupType1, onGroupType0],
        },
        {
            name: 'the agent types both properties after two sets with one filter trade places',
            stored: [
                { ...onGroupType0, value: 'business' },
                { ...onGroupType1, value: 'business' },
            ],
            values: ['business', 'business'],
            typed: [onGroupType1, onGroupType0],
            restored: [onGroupType1, onGroupType0],
        },
        {
            name: 'two sets with one filter trade places and the agent types only the second',
            stored: [
                { ...onGroupType0, value: 'business' },
                { ...onGroupType1, value: 'business' },
            ],
            values: ['business', 'business'],
            typed: [{}, onGroupType0],
            restored: [{}, onGroupType0],
        },
        {
            name: 'two sets that differ only in property type trade places and the agent types only the person one',
            stored: [
                { ...onGroupType1, value: 'pro' },
                { type: 'person', value: 'pro' },
            ],
            values: ['pro', 'pro'],
            typed: [{ type: 'person' }, {}],
            restored: [{ type: 'person' }, {}],
        },
        {
            name: 'two existence filters trade places and the agent types them without a value',
            stored: [
                { ...onGroupType0, operator: 'is_set', value: null },
                { ...onGroupType1, operator: 'is_set', value: null },
            ],
            values: [undefined, undefined],
            typed: [
                { ...onGroupType1, operator: 'is_set' },
                { ...onGroupType0, operator: 'is_set' },
            ],
            restored: [
                { ...onGroupType1, operator: 'is_set' },
                { ...onGroupType0, operator: 'is_set' },
            ],
        },
    ])(
        'merges a group property that two person-aggregated sets hold when $name',
        ({
            stored = planOnTwoGroupTypes,
            storedRollouts = [],
            storedVariants = [],
            values,
            sentRollouts = [],
            sentVariants = [],
            typed = [],
            restored,
        }) => {
            const existing = {
                groups: stored.map((property, index) => ({
                    properties: [{ key: 'plan', operator: 'exact', ...property }],
                    rollout_percentage: storedRollouts[index] ?? 100,
                    variant: storedVariants[index] ?? null,
                })),
            }

            const merged = preserveGroupTargetingFilters(existing, {
                groups: values.map((value, index) => ({
                    properties: [{ key: 'plan', operator: 'exact', value, ...typed[index] }],
                    rollout_percentage: sentRollouts[index] ?? 100,
                    variant: sentVariants[index] ?? null,
                })),
            })

            expect(merged?.groups?.map((group) => group.properties)).toEqual(
                values.map((value, index) => [{ key: 'plan', operator: 'exact', value, ...restored[index] }])
            )
            expect(merged?.groups?.map((group) => group.aggregation_group_type_index ?? null)).toEqual(
                values.map(() => null)
            )
        }
    )

    it.each([
        {
            name: 'a person property differs in value between the sets',
            stored: [
                [
                    { ...onGroupType0, key: 'plan', value: 'enterprise' },
                    { type: 'person', key: 'country', value: 'US' },
                ],
                [
                    { ...onGroupType1, key: 'plan', value: 'pro' },
                    { type: 'person', key: 'country', value: 'CA' },
                ],
            ],
            restoredByProperty: [{}, { type: 'person' }],
        },
        {
            name: 'each set holds the key as a group property and as a person property',
            stored: [
                [
                    { ...onGroupType0, key: 'plan', value: 'enterprise' },
                    { type: 'person', key: 'plan', value: 'pro' },
                ],
                [
                    { ...onGroupType1, key: 'plan', value: 'pro' },
                    { type: 'person', key: 'plan', value: 'free' },
                ],
            ],
            restoredByProperty: [{}, {}],
        },
    ])(
        'types only what two person-aggregated sets agree on when they trade places and $name',
        ({ stored, restoredByProperty }) => {
            const existing = {
                groups: stored.map((properties) => ({
                    properties: properties.map((property) => ({ operator: 'exact', ...property })),
                    rollout_percentage: 100,
                })),
            }
            const swapped = [...stored].reverse()

            const merged = preserveGroupTargetingFilters(existing, {
                groups: swapped.map((properties) => ({
                    properties: properties.map(({ key, value }) => ({ key, operator: 'exact', value })),
                    rollout_percentage: 100,
                })),
            })

            expect(merged?.groups?.map((group) => group.properties)).toEqual(
                swapped.map((properties) =>
                    properties.map(({ key, value }, index) => ({
                        key,
                        operator: 'exact',
                        value,
                        ...restoredByProperty[index],
                    }))
                )
            )
        }
    )

    it.each([
        { name: 'a null rollout', echoed: { rollout_percentage: null }, restored: [0, 1] },
        { name: 'a full rollout', echoed: { rollout_percentage: 100 }, restored: [0, 1] },
        { name: 'a null variant', echoed: { variant: null }, restored: [0, 1] },
        {
            name: 'no rollout for sets stored at rollout 50',
            stored: { rollout_percentage: 50 },
            echoed: {},
            restored: [undefined, undefined],
        },
    ])(
        'types two same-filter person sets by the condition the agent echoes when it sends $name',
        ({ stored = {}, echoed, restored }) => {
            const existing = {
                groups: [onGroupType0, onGroupType1].map((typing) => ({
                    properties: [{ key: 'plan', operator: 'exact', value: 'business', ...typing }],
                    ...stored,
                })),
            }

            const merged = preserveGroupTargetingFilters(existing, {
                groups: existing.groups.map(() => ({
                    properties: [{ key: 'plan', operator: 'exact', value: 'business' }],
                    ...echoed,
                })),
            })

            expect(merged?.groups?.map((group) => group.properties?.[0]?.group_type_index)).toEqual(restored)
        }
    )

    it('passes through multivariate and payloads without restoring from existing', () => {
        const existing = {
            aggregation_group_type_index: 0,
            multivariate: { variants: [{ key: 'control', rollout_percentage: 100 }] },
            payloads: { control: '{"a":1}' },
            groups: existingGroupFlag.groups,
        }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                    rollout_percentage: 50,
                    variant: 'treatment',
                },
            ],
            payloads: { treatment: '{"b":2}' },
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.payloads).toEqual({ treatment: '{"b":2}' })
        expect(merged?.multivariate).toBeUndefined()
        expect(merged?.groups?.[0]?.variant).toBe('treatment')
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
    })

    // On a flag whose sets aggregate differently, only position tells a moved set from an edited
    // one. Position holds while every stored set keeps its keys at its own index.
    it.each([
        {
            name: 'two sets swap places',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [0, 1],
        },
        {
            name: 'the last set is deleted',
            existing: existingPersonThenTwoGroupTypesFlag,
            incoming: {
                groups: [
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [0, 1],
        },
        // Plain rollouts have no keys, so nothing tells which of the two survived.
        {
            name: 'one of two plain rollouts on different group types is deleted',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    { aggregation_group_type_index: 0, properties: [], rollout_percentage: 50 },
                    { aggregation_group_type_index: 1, properties: [], rollout_percentage: 20 },
                ],
            },
            incoming: { groups: [{ properties: [], rollout_percentage: 20 }] },
            unresolved: [0],
        },
        {
            name: 'a set is inserted before the stored sets',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'country', operator: 'exact', value: 'US' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            unresolved: [0, 1, 2],
        },
        {
            name: 'a set gains a property key in place',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'pro' },
                            { key: 'seats', operator: 'gt', value: 10 },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            unresolved: [0, 1],
        },
        {
            name: 'a set is appended after the stored sets',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'country', operator: 'exact', value: 'US' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [2],
        },
        {
            name: 'moved sets state, clear, or imply their own aggregation',
            existing: existingTwoGroupTypeFlag,
            incoming: {
                groups: [
                    {
                        aggregation_group_type_index: 1,
                        properties: [{ key: 'name', operator: 'exact', value: 'acme' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@globex.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'region', operator: 'exact', value: 'eu' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [4],
        },
        {
            name: 'the payload echoes the stored null flag level',
            existing: existingMixedFlag,
            incoming: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [0, 1],
        },
        // A swap of these two sets and an in-place exchange of their values send the same payload.
        {
            name: 'two sets on different aggregations filter on the same key and exchange values',
            existing: existingSameKeyMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [0, 1],
        },
        {
            name: 'one of two sets that filter on the same key changes its value',
            existing: existingSameKeyMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [1],
        },
        // Moving the second set first and dropping its upper bound sends the same first set as
        // dropping the upper bound of the first set in place.
        {
            name: 'a moved set drops one of two filters on a key that both sets share',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'seats', type: 'group', group_type_index: 0, operator: 'gte', value: 5 },
                            { key: 'seats', type: 'group', group_type_index: 0, operator: 'lte', value: 10 },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 1,
                        properties: [
                            { key: 'seats', type: 'group', group_type_index: 1, operator: 'gte', value: 5 },
                            { key: 'seats', type: 'group', group_type_index: 1, operator: 'lte', value: 20 },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'seats', operator: 'gte', value: 5 }], rollout_percentage: 100 },
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'seats', operator: 'gte', value: 5 },
                            { key: 'seats', operator: 'lte', value: 10 },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            unresolved: [0],
        },
        {
            name: 'two sets on different aggregations filter on the same key and value and exchange operators',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key: 'plan', type: 'person', operator: 'exact', value: 'pro' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'icontains', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'icontains', value: 'pro' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            unresolved: [0, 1],
        },
    ])('names each condition set it cannot resolve when $name', ({ existing, incoming, unresolved }) => {
        expect(refusedSets(() => preserveGroupTargetingFilters(existing, incoming))).toEqual(
            unresolved.map((index) => `filters.groups[${index}]`)
        )
    })

    it.each([
        {
            name: 'the payload echoes the stored null flag level',
            existing: existingMixedFlag,
            incoming: {
                aggregation_group_type_index: null,
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@globex.com' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [0, 'group', 0],
                [undefined, 'person', undefined],
            ],
        },
        {
            name: 'two sets that filter on the same key keep their values and omit the exact operator',
            existing: existingSameKeyMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', value: 'free' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', value: 'enterprise' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'person', undefined],
                [0, 'group', 0],
            ],
        },
        {
            name: 'two sets that filter on the same key keep their values',
            existing: existingSameKeyMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'person', undefined],
                [0, 'group', 0],
            ],
        },
        {
            name: 'the sets of a flag on one group type are reordered',
            existing: {
                aggregation_group_type_index: 0,
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 0,
                        properties: [{ key: 'seats', type: 'group', group_type_index: 0, operator: 'gt', value: 10 }],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'seats', operator: 'gt', value: 10 }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'group', 0],
                [undefined, 'group', 0],
            ],
        },
        {
            name: 'a set is appended with its own aggregation',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@globex.com' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 1,
                        properties: [{ key: 'region', operator: 'exact', value: 'eu' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [0, 'group', 0],
                [undefined, 'person', undefined],
                [1, 'group', 1],
            ],
        },
        {
            name: 'two swapped sets state their aggregation',
            existing: existingMixedFlag,
            incoming: {
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 0,
                        properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [null, 'person', undefined],
                [0, 'group', 0],
            ],
        },
        {
            name: 'the sets left after a delete state their aggregation',
            existing: existingPersonThenTwoGroupTypesFlag,
            incoming: {
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 1,
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'pro' },
                            { key: 'seats', operator: 'gt', value: 10 },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [0, 'group', 0],
                [1, 'group', 1],
            ],
        },
        {
            name: 'the payload changes the flag level',
            existing: existingMixedFlag,
            incoming: {
                aggregation_group_type_index: 1,
                groups: [
                    {
                        properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                        rollout_percentage: 100,
                    },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'group', 1],
                [undefined, 'group', 1],
            ],
        },
        // The tool tells agents to echo a null aggregation on the person sets of a mixed flag.
        {
            name: 'a person set echoes its null aggregation and filters on a group property',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: null,
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [{ key: 'plan', operator: 'exact', value: 'pro' }],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: null,
                        properties: [{ key: 'region', operator: 'exact', value: 'eu' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [0, 'group', 0],
                [null, 'group', 1],
            ],
        },
        // An appended set has no source, so the group property of another set must not type it.
        {
            name: 'a set is appended next to a person set that filters on a group property',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'free' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'group', 0],
                [undefined, undefined, undefined],
            ],
        },
        {
            name: 'a person set is deleted and the set left holds its key as a group property',
            existing: {
                groups: [
                    {
                        properties: [
                            { key: 'plan', type: 'person', operator: 'exact', value: 'pro' },
                            { key: 'country', type: 'person', operator: 'exact', value: 'US' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [{ properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 }],
            },
            expected: [[undefined, undefined, undefined]],
        },
        {
            name: 'a set is deleted and the set that moves into its place drops a key',
            existing: {
                groups: [0, 1].map((group_type_index) => ({
                    properties: [
                        { key: 'plan', type: 'group', group_type_index, operator: 'exact', value: 'pro' },
                        { key: 'country', type: 'person', operator: 'exact', value: 'US' },
                    ],
                    rollout_percentage: 100,
                })),
            },
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'pro' },
                            { key: 'country', operator: 'exact', value: 'US' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [undefined, undefined, undefined],
                [undefined, 'group', 1],
            ],
        },
        {
            name: 'two person sets with different keys trade places and one holds the key as a group property',
            existing: existingGroupAndPersonPlanSetsFlag,
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'free' },
                            { key: 'country', operator: 'exact', value: 'US' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [undefined, 'person', undefined],
                [undefined, undefined, undefined],
            ],
        },
        {
            name: 'a person set that holds its key as a group property moves and changes its value',
            existing: existingGroupAndPersonPlanSetsFlag,
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'plan', operator: 'exact', value: 'free' },
                            { key: 'country', operator: 'exact', value: 'US' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        properties: [{ key: 'plan', operator: 'exact', value: 'business' }],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [undefined, 'person', undefined],
                [undefined, undefined, undefined],
            ],
        },
        {
            name: 'a person set moves its group property to another group type',
            existing: {
                groups: [
                    {
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 2, operator: 'exact', value: 'eu' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [[2, 'group', 2]],
        },
        {
            name: 'a person set drops a key and moves its group property to another group type',
            existing: existingPersonSetWithGroupPropertyFlag,
            incoming: {
                groups: [
                    {
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 2, operator: 'exact', value: 'eu' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [[2, 'group', 2]],
        },
        {
            name: 'a set appended to a mixed flag repeats the group property of its person set',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: 0,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: null,
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'us' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                    { properties: [{ key: 'region', operator: 'exact', value: 'eu' }], rollout_percentage: 100 },
                    {
                        properties: [
                            { key: 'region', type: 'group', group_type_index: 1, operator: 'exact', value: 'ca' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            expected: [
                [0, 'group', 0],
                [undefined, 'group', 1],
                [1, 'group', 1],
            ],
        },
        {
            name: 'a stored set that inherits a group flag level moves to persons',
            existing: {
                aggregation_group_type_index: 0,
                groups: [
                    {
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                aggregation_group_type_index: null,
                groups: [{ properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 }],
            },
            expected: [[undefined, undefined, undefined]],
        },
        {
            name: 'a person set changes its rollout next to a group set with the same filters',
            existing: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        aggregation_group_type_index: null,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                    {
                        aggregation_group_type_index: 1,
                        properties: [
                            { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
            incoming: {
                groups: [
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 50 },
                    { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                ],
            },
            expected: [
                [undefined, 'group', 0],
                [1, 'group', 1],
            ],
        },
    ])('keeps each condition set on its own aggregation when $name', ({ existing, incoming, expected }) => {
        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(
            merged?.groups?.map((group) => [
                group.aggregation_group_type_index,
                group.properties?.[0]?.type,
                group.properties?.[0]?.group_type_index,
            ])
        ).toEqual(expected)
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    // The flag evaluator reads each property by its own type, so a group set can hold a person
    // property or a flag dependency. The backend rule only logs that shape, so this test skips the
    // oracle that copies the rule.
    it.each([
        {
            name: 'a person property',
            stored: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
            incoming: { key: 'email', operator: 'icontains', value: '@globex.com' },
            expected: { type: 'person' },
        },
        {
            name: 'a flag dependency',
            stored: [{ key: '42', type: 'flag', operator: 'flag_evaluates_to', value: true }],
            incoming: { key: '42', operator: 'flag_evaluates_to', value: false },
            expected: { type: 'flag' },
        },
        // A new key leaves the set with no source, so the type comes from the stored sets.
        {
            name: 'a flag dependency next to a new key',
            stored: [{ key: '42', type: 'flag', operator: 'flag_evaluates_to', value: true }],
            incoming: { key: '42', operator: 'flag_evaluates_to', value: true },
            added: [{ key: 'seats', operator: 'gt', value: 10 }],
            expected: { type: 'flag' },
        },
    ])('restores the stored type of $name in a group set', ({ stored, incoming, added = [], expected }) => {
        const existing = {
            aggregation_group_type_index: 0,
            groups: [{ aggregation_group_type_index: 0, properties: stored, rollout_percentage: 100 }],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [{ properties: [incoming, ...added], rollout_percentage: 100 }],
        })

        expect(merged?.groups?.[0]?.properties?.[0]).toEqual({ ...incoming, ...expected })
    })

    // The property index has to follow the set, not the property it matched in the old group
    // type.
    it.each([
        {
            name: 'the set carries the new index',
            flag: { aggregation_group_type_index: 1 },
            group: { aggregation_group_type_index: 1 },
            property: {},
        },
        { name: 'only the flag level carries it', flag: { aggregation_group_type_index: 1 }, group: {}, property: {} },
        {
            name: 'the agent echoes back the old property index',
            flag: { aggregation_group_type_index: 1 },
            group: { aggregation_group_type_index: 1 },
            property: { type: 'group', group_type_index: 0 },
        },
        {
            name: 'only the property carries it',
            flag: {},
            group: {},
            property: { type: 'group', group_type_index: 1 },
        },
        {
            name: 'the payload echoes the stored flag level and only the property carries it',
            flag: { aggregation_group_type_index: 0 },
            group: {},
            property: { type: 'group', group_type_index: 1 },
        },
    ])('retargets a condition set to another group type when $name', ({ flag, group, property }) => {
        const merged = preserveGroupTargetingFilters(existingGroupFlag, {
            ...flag,
            groups: [
                {
                    ...group,
                    properties: [{ key: 'plan', operator: 'exact', value: 'pro', ...property }],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties?.[0]).toEqual({
            key: 'plan',
            type: 'group',
            group_type_index: 1,
            operator: 'exact',
            value: 'pro',
        })
        expect(aggregationViolations(existingGroupFlag, merged)).toEqual([])
    })

    // The merge walks both sides by index. A malformed entry on either side must not throw.
    it.each([
        { name: 'null groups on the existing flag', existing: { groups: null } },
        { name: 'a null condition set', existing: { groups: [null] } },
        { name: 'a condition set that is an array', existing: { groups: [[]] } },
        { name: 'null properties', existing: { groups: [{ properties: null }] } },
    ])('passes an incoming payload through unchanged when the existing flag has $name', ({ existing }) => {
        const incoming = { groups: [{ properties: [{ key: 'plan', operator: 'exact', value: 'pro' }] }] }

        expect(preserveGroupTargetingFilters(existing as FlagFilters, incoming)).toEqual(incoming)
    })

    // A collapse leaves every set without a source. Each property takes its type from the stored
    // set that holds its key.
    it('restores a property type from another set when two sets collapse into one', () => {
        const existing = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'seats', type: 'person', operator: 'gt', value: 10 }],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    properties: [
                        { key: 'seats', operator: 'gt', value: 25 },
                        { key: 'email', operator: 'icontains', value: '@globex.com' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('person')
        expect(merged?.groups?.[0]?.properties?.[1]?.type).toBe('person')
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    it('restores a person type from another set when the source holds the key only as a group property', () => {
        const existing = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                    ],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: null,
                    properties: [
                        { key: 'plan', type: 'person', operator: 'exact', value: 'free' },
                        { key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'plan', operator: 'exact', value: 'enterprise' }],
                    rollout_percentage: 100,
                },
                {
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'free' },
                        { key: 'email', operator: 'icontains', value: '@acme.com' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('person')
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    it('restores a person type in a moved set that states its own group type', () => {
        const existing = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        { key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' },
                    ],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: 1,
                    properties: [{ key: 'seats', type: 'group', group_type_index: 1, operator: 'gt', value: 10 }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    aggregation_group_type_index: 1,
                    properties: [{ key: 'seats', operator: 'gt', value: 10 }],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'enterprise' },
                        { key: 'email', operator: 'icontains', value: '@acme.com' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(
            merged?.groups?.map((group) =>
                group.properties?.map((property) => [property.key, property.type, property.group_type_index])
            )
        ).toEqual([
            [['seats', 'group', 1]],
            [
                ['plan', 'group', 0],
                ['email', 'person', undefined],
            ],
        ])
    })

    it('restores a flag dependency in a group set when another set changes its keys', () => {
        const existing = {
            aggregation_group_type_index: 0,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        { key: '42', type: 'flag', operator: 'flag_evaluates_to', value: true },
                    ],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: 0,
                    properties: [{ key: 'seats', type: 'group', group_type_index: 0, operator: 'gt', value: 10 }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'enterprise' },
                        { key: '42', operator: 'flag_evaluates_to', value: true },
                    ],
                    rollout_percentage: 100,
                },
                {
                    properties: [
                        { key: 'seats', operator: 'gt', value: 10 },
                        { key: 'region', operator: 'exact', value: 'eu' },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.properties?.[1]).toEqual({
            key: '42',
            type: 'flag',
            operator: 'flag_evaluates_to',
            value: true,
        })
    })

    it('accepts group properties when both type and index are present (no strip)', () => {
        const incoming = {
            aggregation_group_type_index: 0,
            groups: [
                {
                    properties: [
                        {
                            key: 'workspace_id',
                            type: 'group',
                            group_type_index: 0,
                            operator: 'exact',
                            value: 'ws-1',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(null, incoming)
        expect(merged).toEqual(incoming)
    })
})
