import { describe, expect, it } from 'vitest'

import { type FlagFilters, preserveGroupTargetingFilters } from '@/tools/featureFlags/preserveGroupTargeting'

const PERSON_AGGREGATED_PROPERTY_TYPES = ['person', 'cohort', 'flag']

/**
 * Mirrors check_property_types_match_aggregation in
 * products/feature_flags/backend/filters_validation.py, over the state that validator sees:
 * the flag level the backend keeps when the payload omits it, then each set's own key. The check
 * skips a property with no type. A test asserts the fields of a property left untyped instead.
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

    it('restores group type from the set it came from when condition groups collapse', () => {
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

    // The set aggregates on a group type, which decides the property type. The merge never reads
    // the candidates, whichever operator the agent sends.
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
    // API rejects. Restoring the type would carry that contradiction into the new payload.
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

    // A reordered payload carries no flag-level key and no set-level index. A positional restore
    // would read the aggregation of the wrong set.
    it('attributes reordered condition sets to the set each one came from', () => {
        const merged = preserveGroupTargetingFilters(existingMixedFlag, {
            groups: [
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
            ],
        })

        expect(merged).toEqual({
            groups: [
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: 0,
                    properties: [{ key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'pro' }],
                    rollout_percentage: 100,
                },
            ],
        })
        expect(aggregationViolations(existingMixedFlag, merged)).toEqual([])
    })

    it.each([
        {
            name: 'a set is deleted',
            existing: existingMixedFlag,
            groups: [
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        },
        {
            name: 'a set is inserted before an existing one',
            existing: existingGroupFlag,
            groups: [
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
            ],
        },
        {
            name: 'two sets aggregating on different group types swap places',
            existing: existingTwoGroupTypeFlag,
            groups: [
                { properties: [{ key: 'name', operator: 'exact', value: 'globex' }], rollout_percentage: 100 },
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
            ],
        },
    ])('leaves no self-contradictory condition set when $name', ({ existing, groups }) => {
        const merged = preserveGroupTargetingFilters(existing, { groups })

        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    // The property index has to follow the set, not the property it matched in the old group
    // type.
    it.each([
        { name: 'the set carries the new index', group: { aggregation_group_type_index: 1 }, property: {} },
        { name: 'only the flag level carries it', group: {}, property: {} },
        {
            name: 'the agent echoes back the old property index',
            group: { aggregation_group_type_index: 1 },
            property: { type: 'group', group_type_index: 0 },
        },
    ])('retargets a condition set to another group type when $name', ({ group, property }) => {
        const merged = preserveGroupTargetingFilters(existingGroupFlag, {
            aggregation_group_type_index: 1,
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

    it('restores set aggregation from the same index when every property key changed', () => {
        const merged = preserveGroupTargetingFilters(existingMixedFlag, {
            groups: [
                { properties: [{ key: 'seats', operator: 'gt', value: 10 }], rollout_percentage: 100 },
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
    })

    // Position is the only evidence left of which existing set each one came from.
    it('restores each set aggregation by position when every property key changed in both sets', () => {
        const merged = preserveGroupTargetingFilters(existingMixedFlag, {
            groups: [
                { properties: [{ key: 'seats', operator: 'gt', value: 10 }], rollout_percentage: 100 },
                { properties: [{ key: 'country', operator: 'exact', value: 'US' }], rollout_percentage: 100 },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBeUndefined()
        expect(aggregationViolations(existingMixedFlag, merged)).toEqual([])
    })

    // The first set shares one key with the set at its own index and two with the other set.
    // Its own index wins. A set that gained a key therefore does not take the other set's group type.
    it('keeps each set at its own index when another set is a stronger key match', () => {
        const existing = {
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
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 1, operator: 'exact', value: 'pro' },
                        { key: 'seats', type: 'group', group_type_index: 1, operator: 'gt', value: 10 },
                    ],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                {
                    properties: [
                        { key: 'plan', operator: 'exact', value: 'enterprise' },
                        { key: 'seats', operator: 'gt', value: 25 },
                    ],
                    rollout_percentage: 100,
                },
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBe(1)
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    // A set with no properties has no key to match. Only elimination decides which existing set
    // it came from.
    it('attributes a condition set with no properties when the sets are reordered', () => {
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
                { aggregation_group_type_index: 1, properties: [], rollout_percentage: 50 },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                { properties: [], rollout_percentage: 50 },
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
            ],
        })

        expect(merged?.groups?.[0]?.aggregation_group_type_index).toBe(1)
        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.properties?.[0]?.group_type_index).toBe(0)
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

    // Only one of the two sets can own the set they were split from. Both descend from it.
    it('restores group targeting for a condition set split off another set', () => {
        const existing = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'plan', type: 'group', group_type_index: 0, operator: 'exact', value: 'enterprise' },
                        { key: 'seats', type: 'group', group_type_index: 0, operator: 'gt', value: 10 },
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

        const merged = preserveGroupTargetingFilters(existing, {
            groups: [
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                { properties: [{ key: 'seats', operator: 'gt', value: 25 }], rollout_percentage: 50 },
            ],
        })

        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBe(0)
        expect(merged?.groups?.[1]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[1]?.properties?.[0]?.group_type_index).toBe(0)
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    // An unattributed set has no source to read an aggregation index from. The existing set at the
    // tied set's index shares no key with it. Elimination takes the first case and position takes
    // the second, and neither may pair the two.
    it.each([
        { name: 'the other sets keep their keys', otherKeys: ['email', 'email'] },
        { name: 'the other sets change every key', otherKeys: ['plan', 'country'] },
    ])('leaves a set unattributed when two existing sets match it equally and $name', ({ otherKeys }) => {
        const existing = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: 0,
                    properties: [
                        { key: 'email', type: 'group', group_type_index: 0, operator: 'icontains', value: '@acme.com' },
                    ],
                    rollout_percentage: 100,
                },
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@globex.com' }],
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
                ...otherKeys.map((key) => ({
                    properties: [{ key, operator: 'icontains', value: '@globex.com' }],
                    rollout_percentage: 100,
                })),
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@initech.com' }],
                    rollout_percentage: 25,
                },
            ],
        })

        expect(merged?.groups?.[2]?.aggregation_group_type_index).toBeUndefined()
        expect(merged?.groups?.[2]?.properties?.[0]?.type).toBe('person')
        expect(aggregationViolations(existing, merged)).toEqual([])
    })

    // The claimed source set holds only one of the two keys. The merge can type the other
    // property only from the set that still holds it.
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

    it('restores a person property type from a source set another set already claimed', () => {
        const merged = preserveGroupTargetingFilters(existingMixedFlag, {
            groups: [
                { properties: [{ key: 'plan', operator: 'exact', value: 'pro' }], rollout_percentage: 100 },
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
                {
                    properties: [{ key: 'email', operator: 'icontains', value: '@globex.com' }],
                    rollout_percentage: 50,
                },
            ],
        })

        expect(merged?.groups?.[2]?.properties?.[0]?.type).toBe('person')
        expect(merged?.groups?.[2]?.aggregation_group_type_index).toBeUndefined()
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
