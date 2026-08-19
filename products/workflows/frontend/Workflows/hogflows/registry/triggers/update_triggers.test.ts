import './group_updates'
import './person_updates'

import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('person and group update triggers', () => {
    const getTriggerType = (value: string): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === value)
        if (!triggerType) {
            throw new Error(`${value} trigger type not registered`)
        }
        return triggerType
    }

    it.each([
        ['person-updates', 'cdp-person-updates'],
        ['group-updates', 'cdp-group-updates'],
    ])('%s is gated behind the %s feature flag', (value, flag) => {
        expect(getTriggerType(value).featureFlag).toBe(flag)
    })

    it.each(['person-updates', 'group-updates'])('%s builds a config its own matchConfig recognizes', (value) => {
        const triggerType = getTriggerType(value)
        const config = triggerType.buildConfig()

        expect(config.type).toBe(value)
        expect(triggerType.matchConfig!(config)).toBe(true)
    })

    describe('group-updates validation', () => {
        it.each([
            {
                name: 'a missing group type, which would leave the workflow inert',
                config: { type: 'group-updates', filters: { properties: [] } },
                expected: { valid: false, errors: { group_type_index: 'Please select a group type' } },
            },
            {
                name: 'a group type of 0, which is falsy but valid',
                config: { type: 'group-updates', group_type_index: 0, filters: { properties: [] } },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'another trigger type, which it does not own',
                config: { type: 'event', filters: {} },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(getTriggerType('group-updates').validate!(config as any)).toEqual(expected)
        })
    })
})
