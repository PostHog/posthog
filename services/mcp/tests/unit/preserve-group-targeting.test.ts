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

        expect(merged.aggregation_group_type_index).toBe(0)
        expect(merged.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged.groups?.[0]?.properties?.[0]?.group_type_index).toBe(0)
        expect(merged.groups?.[0]?.properties?.[0]?.value).toBe('pro')
        expect(merged.groups?.[0]?.rollout_percentage).toBe(50)
    })

    it('does not override explicit person type', () => {
        const incoming = {
            groups: [
                {
                    properties: [{ key: 'email', type: 'person', operator: 'icontains', value: '@acme.com' }],
                    rollout_percentage: 100,
                },
            ],
        }

        const merged = preserveGroupTargetingFilters(existingGroupFlag, incoming)

        expect(merged.aggregation_group_type_index).toBe(0)
        expect(merged.groups?.[0]?.properties?.[0]?.type).toBe('person')
        // person props should not inherit group_type_index unless type is group
        expect(merged.groups?.[0]?.properties?.[0]?.group_type_index).toBeUndefined()
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

        expect(merged.aggregation_group_type_index).toBe(1)
        expect(merged.groups?.[0]?.properties?.[0]?.group_type_index).toBe(1)
        expect(merged.groups?.[0]?.properties?.[0]?.type).toBe('group')
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

        expect(merged.aggregation_group_type_index).toBe(2)
        expect(merged.groups?.[0]?.properties?.[0]?.type).toBe('group')
        expect(merged.groups?.[0]?.properties?.[0]?.group_type_index).toBe(2)
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

        expect(merged.aggregation_group_type_index).toBeUndefined()
        // Without existing group context we do not invent type: group
        expect(merged.groups?.[0]?.properties?.[0]?.type).toBeUndefined()
    })

    it('accepts group properties in create-shaped payloads (schema regression guard via shape)', () => {
        // Ensure we never strip type/group_type_index when both are present.
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
