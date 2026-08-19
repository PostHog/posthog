import { PropertyType } from '~/types'

import {
    accountCustomPropertyChangedFilters,
    accountCustomPropertyFrequencyOptions,
    accountRelationshipChangedFilters,
    accountRelationshipFrequencyOptions,
    accountTagAddedFilters,
    customPropertyDisplayTypeToPropertyType,
    getAccountCustomPropertyChangedConditions,
    getAccountCustomPropertyValueFilters,
    getAccountRelationshipChangeType,
    getSelectedPropertyNames,
    getSelectedRelationshipNames,
    getSelectedTags,
} from './customer_analytics'
import { EventTriggerConfig, getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('customer analytics triggers', () => {
    const getTriggerType = (value: string): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === value)
        if (!triggerType) {
            throw new Error(`${value} trigger type not registered`)
        }
        return triggerType
    }

    it.each(['account_tag_added', 'account_custom_property_changed', 'account_relationship_changed'])(
        '%s buildConfig produces a config recognized by matchConfig',
        (value) => {
            const triggerType = getTriggerType(value)
            expect(triggerType.matchConfig!(triggerType.buildConfig())).toBe(true)
        }
    )

    it("the account triggers do not claim each other's configs", () => {
        const triggers = [
            getTriggerType('account_tag_added'),
            getTriggerType('account_custom_property_changed'),
            getTriggerType('account_relationship_changed'),
        ]
        for (const trigger of triggers) {
            for (const otherTrigger of triggers) {
                expect(trigger.matchConfig!(otherTrigger.buildConfig())).toBe(trigger === otherTrigger)
            }
        }
    })

    it.each([
        {
            name: 'array value',
            properties: [{ key: 'tag', value: ['vip', 'enterprise'], operator: 'exact', type: 'event' }],
            expected: ['vip', 'enterprise'],
        },
        {
            name: 'scalar value',
            properties: [{ key: 'tag', value: 'vip', operator: 'exact', type: 'event' }],
            expected: ['vip'],
        },
        { name: 'no tag property', properties: [], expected: [] },
        {
            name: 'non-string values',
            properties: [{ key: 'tag', value: [1, null], operator: 'exact', type: 'event' }],
            expected: [],
        },
    ])('getSelectedTags handles $name', ({ properties, expected }) => {
        const config: EventTriggerConfig = { type: 'event', filters: { properties } }
        expect(getSelectedTags(config)).toEqual(expected)
    })

    it('omits the tag property filter when no tags are selected', () => {
        expect(accountTagAddedFilters([]).properties).toEqual([])
        expect(accountTagAddedFilters(['vip']).properties).toEqual([
            { key: 'tag', value: ['vip'], operator: 'exact', type: 'event' },
        ])
    })

    it.each([
        {
            name: 'array value',
            properties: [{ key: 'property_name', value: ['Plan', 'MRR'], operator: 'exact', type: 'event' }],
            expected: ['Plan', 'MRR'],
        },
        {
            name: 'scalar value',
            properties: [{ key: 'property_name', value: 'Plan', operator: 'exact', type: 'event' }],
            expected: ['Plan'],
        },
        { name: 'no property filter', properties: [], expected: [] },
        {
            name: 'non-string values',
            properties: [{ key: 'property_name', value: [1, null], operator: 'exact', type: 'event' }],
            expected: [],
        },
    ])('getSelectedPropertyNames handles $name', ({ properties, expected }) => {
        const config: EventTriggerConfig = { type: 'event', filters: { properties } }
        expect(getSelectedPropertyNames(config)).toEqual(expected)
    })

    it('builds one nested event-filter group per selected property', () => {
        expect(accountCustomPropertyChangedFilters([])).toMatchObject({
            events: [{ id: '$account_custom_property_changed' }],
            properties: [],
        })
        expect(accountCustomPropertyChangedFilters(['Plan'])).toMatchObject({
            events: [
                {
                    id: '$account_custom_property_changed',
                    properties: [{ key: 'property_name', value: 'Plan', operator: 'exact', type: 'event' }],
                },
            ],
            properties: [],
        })
    })

    it('exposes current value filters separately from the managed property picker filter', () => {
        const currentValueFilter = { key: 'current_value', value: 'enterprise', operator: 'exact', type: 'event' }
        const config: EventTriggerConfig = {
            type: 'event',
            filters: {
                properties: [
                    { key: 'property_name', value: ['Plan'], operator: 'exact', type: 'event' },
                    currentValueFilter,
                ],
            },
        }

        expect(getAccountCustomPropertyValueFilters(config)).toEqual([currentValueFilter])
    })

    it('upgrades legacy top-level filters without losing the selected property condition', () => {
        const currentValueFilter = { key: 'current_value', value: 'enterprise', operator: 'exact', type: 'event' }
        const filters = accountCustomPropertyChangedFilters(['Plan', 'Seats'], {
            properties: [
                { key: 'property_name', value: ['Plan'], operator: 'exact', type: 'event' },
                currentValueFilter,
            ],
            filter_test_accounts: true,
        })

        expect(filters.properties).toEqual([])
        expect(filters.events).toMatchObject([
            {
                properties: [
                    { key: 'property_name', value: 'Plan', operator: 'exact', type: 'event' },
                    currentValueFilter,
                ],
            },
            {
                properties: [{ key: 'property_name', value: 'Seats', operator: 'exact', type: 'event' }],
            },
        ])
        expect(filters.filter_test_accounts).toBe(true)
    })

    it('round-trips independently typed OR groups', () => {
        const planFilter = { key: 'current_value', value: 'enterprise', operator: 'exact', type: 'event' }
        const seatsFilter = { key: 'current_value', value: 5, operator: 'gt', type: 'event' }
        const filters = accountCustomPropertyChangedFilters(['Plan', 'Seats'], {}, [
            { propertyName: 'Plan', valueFilters: [planFilter] },
            { propertyName: 'Seats', valueFilters: [seatsFilter] },
        ])
        const config: EventTriggerConfig = { type: 'event', filters }

        expect(getSelectedPropertyNames(config)).toEqual(['Plan', 'Seats'])
        expect(getAccountCustomPropertyChangedConditions(config)).toEqual([
            { propertyName: 'Plan', valueFilters: [planFilter] },
            { propertyName: 'Seats', valueFilters: [seatsFilter] },
        ])
    })

    it.each([
        ['text', PropertyType.String],
        ['select', PropertyType.String],
        ['number', PropertyType.Numeric],
        ['currency', PropertyType.Numeric],
        ['percent', PropertyType.Numeric],
        ['boolean', PropertyType.Boolean],
        ['date', PropertyType.DateTime],
        ['datetime', PropertyType.DateTime],
    ] as const)('maps the %s custom property display type to %s operators', (displayType, expected) => {
        expect(customPropertyDisplayTypeToPropertyType(displayType)).toBe(expected)
    })

    it.each([
        {
            name: 'array value',
            properties: [
                { key: 'relationship_name', value: ['CSM', 'Account owner'], operator: 'exact', type: 'event' },
            ],
            expected: ['CSM', 'Account owner'],
        },
        {
            name: 'scalar value',
            properties: [{ key: 'relationship_name', value: 'CSM', operator: 'exact', type: 'event' }],
            expected: ['CSM'],
        },
        { name: 'no relationship filter', properties: [], expected: [] },
        {
            name: 'non-string values',
            properties: [{ key: 'relationship_name', value: [1, null], operator: 'exact', type: 'event' }],
            expected: [],
        },
    ])('getSelectedRelationshipNames handles $name', ({ properties, expected }) => {
        const config: EventTriggerConfig = { type: 'event', filters: { properties } }
        expect(getSelectedRelationshipNames(config)).toEqual(expected)
    })

    it('omits the relationship filter when no relationships are selected', () => {
        expect(accountRelationshipChangedFilters([]).properties).toEqual([])
        expect(accountRelationshipChangedFilters(['CSM']).properties).toEqual([
            { key: 'relationship_name', value: ['CSM'], operator: 'exact', type: 'event' },
        ])
    })

    it('preserves the change type filter when the relationship selection changes', () => {
        const changeTypeFilter = { key: 'change_type', value: 'assigned', operator: 'exact', type: 'event' }
        const filters = accountRelationshipChangedFilters(['CSM'], {
            properties: [changeTypeFilter],
            filter_test_accounts: true,
        })
        const config: EventTriggerConfig = { type: 'event', filters }

        expect(filters.properties).toEqual([
            { key: 'relationship_name', value: ['CSM'], operator: 'exact', type: 'event' },
            changeTypeFilter,
        ])
        expect(filters.filter_test_accounts).toBe(true)
        expect(getAccountRelationshipChangeType(config)).toBe('assigned')
    })

    it('replaces the change type filter without changing the selected relationships', () => {
        const filters = accountRelationshipChangedFilters(['CSM'], {}, 'unassigned')

        expect(filters.properties).toEqual([
            { key: 'relationship_name', value: ['CSM'], operator: 'exact', type: 'event' },
            { key: 'change_type', value: 'unassigned', operator: 'exact', type: 'event' },
        ])
    })

    it('clears the change type filter without changing the selected relationships', () => {
        const filters = accountRelationshipChangedFilters(
            ['CSM'],
            {
                properties: [{ key: 'change_type', value: 'assigned', operator: 'exact', type: 'event' }],
            },
            null
        )

        expect(filters.properties).toEqual([
            { key: 'relationship_name', value: ['CSM'], operator: 'exact', type: 'event' },
        ])
    })

    // The hash templates are evaluated as Hog against the trigger event at runtime — a typo'd
    // property reference resolves to null for every event and masks all accounts as one.
    it.each([
        { options: accountCustomPropertyFrequencyOptions, field: 'event.properties.property_name' },
        { options: accountRelationshipFrequencyOptions, field: 'event.properties.relationship_name' },
    ])('frequency hashes key on the account and changed field from the trigger event', ({ options, field }) => {
        const maskingOptions = options.filter((option) => option.value !== null)
        expect(maskingOptions.length).toBeGreaterThan(0)
        for (const option of maskingOptions) {
            expect(option.value).toContain('event.properties.account_id')
            expect(option.value).toContain(field)
        }
    })
})
