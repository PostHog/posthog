import { HogFlowAction } from '../types'
import {
    TRIGGER_VOLUME_DAYS,
    eventTriggerVolumeFilters,
    eventTriggerVolumeQuery,
    hogFlowStartsAiRuns,
} from './triggerVolume'

function functionAction(templateId: string): HogFlowAction {
    return {
        id: 'function_1',
        type: 'function',
        name: 'Step',
        description: '',
        config: { template_id: templateId, inputs: {} },
    } as HogFlowAction
}

describe('triggerVolume', () => {
    describe('eventTriggerVolumeFilters', () => {
        const cases: [string, Record<string, any>, boolean][] = [
            [
                'an event trigger with an event',
                { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
                true,
            ],
            ['an event trigger with only properties', { type: 'event', filters: { properties: [{}] } }, true],
            ['an event trigger with nothing configured', { type: 'event', filters: {} }, false],
            [
                // Internal events are never written to the events table, so no query can count them.
                'an internal event trigger',
                {
                    type: 'internal-event',
                    filters: { source: 'internal-events', events: [{ id: '$slack_message_received' }] },
                },
                false,
            ],
            ['a batch trigger', { type: 'batch', filters: { properties: [] } }, false],
            ['a schedule trigger', { type: 'schedule' }, false],
        ]

        it.each(cases)('%s', (_name, config, expected) => {
            const action = { id: 'trigger_1', type: 'trigger', name: 'Trigger', description: '', config }
            expect(eventTriggerVolumeFilters(action as HogFlowAction) !== null).toBe(expected)
        })

        it('is null for a step that is not the trigger', () => {
            expect(eventTriggerVolumeFilters(functionAction('template-webhook'))).toBeNull()
        })
    })

    describe('hogFlowStartsAiRuns', () => {
        it.each([
            ['an AI task step', 'template-posthog-create-task', true],
            ['a scout step', 'template-posthog-run-scout', true],
            ['a webhook step', 'template-webhook', false],
        ])('%s', (_name, templateId, expected) => {
            expect(hogFlowStartsAiRuns({ actions: [functionAction(templateId as string)] })).toBe(expected)
        })

        it('is false for a workflow with no steps', () => {
            expect(hogFlowStartsAiRuns({ actions: [] })).toBe(false)
            expect(hogFlowStartsAiRuns(null)).toBe(false)
        })
    })

    describe('eventTriggerVolumeQuery', () => {
        it('counts the trigger events over the window the copy promises', () => {
            const query = eventTriggerVolumeQuery({
                events: [{ id: 'purchase', type: 'events' }],
                filter_test_accounts: true,
            })

            expect(query.dateRange?.date_from).toBe(`-${TRIGGER_VOLUME_DAYS}d`)
            expect(query.interval).toBe('day')
            expect(query.filterTestAccounts).toBe(true)
            expect(JSON.stringify(query.properties)).toContain("event = 'purchase'")
        })
    })
})
