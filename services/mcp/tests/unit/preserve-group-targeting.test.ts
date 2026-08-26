import { describe, expect, it } from 'vitest'

import { preserveGroupTargetingFilters } from '@/tools/featureFlags/preserveGroupTargeting'

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
        // Same-index set-level aggregation is restored when omitted.
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

        // Flag-level aggregation still restored when omitted (partial update of props).
        // But the condition set must not carry group aggregation around person props.
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

    it('still restores a non-group property type in a set pinned to person aggregation', () => {
        const existingPersonSetFlag = {
            aggregation_group_type_index: 0,
            groups: [
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }
        const incoming = {
            aggregation_group_type_index: null,
            groups: [
                {
                    aggregation_group_type_index: null,
                    properties: [{ key: 'email', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingPersonSetFlag, incoming)

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('person')
    })

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

    it('restores group type via cross-group key match when condition groups collapse', () => {
        // Existing: person email in groups[0], group plan in groups[1].
        // Incoming: single group with only partial plan — must hit cross-group fallback.
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

    it.each([
        { name: 'the operator matches the group-typed candidate', operator: 'exact', value: 'New Name' },
        { name: 'the operator matches neither candidate', operator: 'regex', value: '.*' },
    ])('restores group type and index for a duplicate key when $name', ({ operator, value }) => {
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
                    properties: [{ key: 'name', operator, value }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existing, incoming)

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged?.groups?.[0]?.properties?.[0]?.value).toBe(value)
    })

    it('does not copy set-level aggregation onto a newly appended condition set', () => {
        // Existing: one org-aggregated set, no flag-level index.
        // Incoming: append a second set with person-typed email and no aggregation key.
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
        // Second set is explicitly person-typed → pin to person aggregation (null).
        expect(merged?.groups?.[1]?.aggregation_group_type_index).toBeNull()
        expect(merged?.groups?.[1]?.properties?.[0]?.type).toBe('person')
    })

    it('restores property group_type_index from matched existing property over flag aggregation', () => {
        const existing = {
            // No flag-level aggregation — property carries group_type_index: 1
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

        expect(merged?.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged?.groups?.[0]?.properties?.[0]?.group_type_index).toBe(1)
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
