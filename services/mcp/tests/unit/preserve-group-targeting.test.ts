import { describe, expect, it } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import { type FlagFilters, preserveGroupTargetingFilters } from '@/tools/featureFlags/preserveGroupTargeting'

const PERSON_AGGREGATED_PROPERTY_TYPES = ['person', 'cohort', 'flag']

/**
 * Mirrors check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py, over the state that validator sees:
 * the flag level the backend keeps when the payload omits it, then each set's own key. This helper
 * skips a property with no type, which the backend rule reports. A test asserts the fields of a
 * property left untyped instead.
 */
function aggregationViolations(existing: FlagFilters, merged: FlagFilters | null | undefined): string[] {
    const violations: string[] = []
    const flagLevel =
        merged && 'aggregation_group_type_index' in merged
            ? merged.aggregation_group_type_index
            : existing.aggregation_group_type_index
    for (const [groupIndex, group] of (merged?.groups ?? []).entries()) {
        const aggregation = 'aggregation_group_type_index' in group ? group.aggregation_group_type_index : flagLevel
        for (const [propertyIndex, property] of (group.properties ?? []).entries()) {
            const path = `groups[${groupIndex}].properties[${propertyIndex}]`
            if (typeof property.type !== 'string') {
                continue
            }
            if (aggregation === undefined || aggregation === null) {
                if (!PERSON_AGGREGATED_PROPERTY_TYPES.includes(property.type)) {
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

    // A person-aggregated set cannot hold a group property. A key that matches an existing
    // group property must not resurrect one, or the API error names a field the agent never sent.
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
        // Collapsing two sets into one leaves the surviving set at a position it did not hold.
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

    // The set aggregates on person, so the candidates decide the type. The operator picks
    // between two candidates that share a key. Without an operator match, the first one wins.
    it.each([
        { name: 'the operator matches the cohort candidate', operator: 'in', expectedType: 'cohort' },
        { name: 'the operator matches the person candidate', operator: 'icontains', expectedType: 'person' },
        { name: 'the operator matches neither candidate', operator: 'regex', expectedType: 'person' },
    ])('picks a duplicate-key candidate by operator when $name', ({ operator, expectedType }) => {
        const existing = {
            groups: [
                {
                    properties: [
                        { key: 'name', type: 'person', operator: 'icontains', value: 'acme' },
                        { key: 'name', type: 'cohort', operator: 'in', value: 42 },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'name', operator, value: 'acme' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe(expectedType)
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

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

    // The existing flag holds a group property with no aggregation index anywhere, which the
    // backend validator reports. Restoring the type would carry that contradiction into the new payload.
    it('does not restore a group property type into a set with no group aggregation', () => {
        const existing = {
            groups: [
                {
                    properties: [
                        {
                            key: 'region',
                            type: 'group',
                            group_type_index: 1,
                            operator: 'exact',
                            value: 'us',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'region', operator: 'exact', value: 'eu' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBeUndefined()
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBeUndefined()
    })

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
            unresolved: [],
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
            unresolved: [],
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
    ])('restores the stored type of $name in a group set', ({ stored, incoming, expected }) => {
        const existing = {
            aggregation_group_type_index: 0,
            groups: [{ aggregation_group_type_index: 0, properties: stored, rollout_percentage: 100 }],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [{ properties: [incoming], rollout_percentage: 100 }],
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
