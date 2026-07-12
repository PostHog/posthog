import { accountTagAddedFilters, getSelectedTags } from './customer_analytics'
import { EventTriggerConfig, getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('customer analytics triggers', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'account_tag_added')
        if (!triggerType) {
            throw new Error('account_tag_added trigger type not registered')
        }
        return triggerType
    }

    it('buildConfig produces a config recognized by matchConfig', () => {
        const triggerType = getTriggerType()
        expect(triggerType.matchConfig!(triggerType.buildConfig())).toBe(true)
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
})
