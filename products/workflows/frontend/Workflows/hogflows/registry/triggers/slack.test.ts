import './slack'

import { PropertyOperator } from '~/types'

import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('slack message trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'slack-message')
        if (!triggerType) {
            throw new Error('Slack message trigger type not registered')
        }
        return triggerType
    }

    describe('validate', () => {
        it.each([
            {
                name: 'no channel filter',
                config: { type: 'slack-message', filters: { properties: [] } },
                expected: { valid: false, errors: { channel: 'Please pick a Slack channel' } },
            },
            {
                name: 'channel filter present',
                config: {
                    type: 'slack-message',
                    filters: { properties: [{ key: 'channel', value: ['C0ALERTS'] }] },
                },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'other filters do not stand in for a channel',
                config: { type: 'slack-message', filters: { properties: [{ key: 'text', value: ['fire'] }] } },
                expected: { valid: false, errors: { channel: 'Please pick a Slack channel' } },
            },
            {
                name: 'non slack-message config returns null',
                config: { type: 'event', filters: {} },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(getTriggerType().validate!(config as any)).toEqual(expected)
        })
    })

    it('is gated behind the slack-workflow-triggers feature flag', () => {
        expect(getTriggerType().featureFlag).toBe('slack-workflow-triggers')
    })

    it('buildConfig produces a config recognized by matchConfig', () => {
        // A mismatch here leaves the editor unable to identify its own trigger, so it silently falls
        // back to the raw filter editor.
        const triggerType = getTriggerType()
        const config = triggerType.buildConfig()
        expect(config.type).toBe('slack-message')
        expect(triggerType.matchConfig!(config)).toBe(true)
    })

    it('excludes bot posts by default so a workflow cannot retrigger on its own message', () => {
        const properties = getTriggerType().buildConfig().filters.properties
        expect(properties).toContainEqual(
            expect.objectContaining({ key: 'bot_id', operator: PropertyOperator.IsNotSet })
        )
    })
})
