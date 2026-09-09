import { HogFlowAction } from '../types'
import {
    TRIGGER_VOLUME_DAYS,
    countAiRunSteps,
    eventTriggerVolumeFilters,
    eventTriggerVolumeQuery,
} from './triggerVolume'

function functionAction(templateId: string, id: string = 'function_1'): HogFlowAction {
    return {
        id,
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

    describe('countAiRunSteps', () => {
        it.each([
            ['an AI task step', 'template-posthog-create-task', 1],
            ['a scout step', 'template-posthog-run-scout', 1],
            ['a webhook step', 'template-webhook', 0],
        ])('%s', (_name, templateId, expected) => {
            expect(countAiRunSteps({ actions: [functionAction(templateId as string)] })).toBe(expected)
        })

        // Each step a run reaches creates its own task, so two steps reach the daily cap at half
        // the runs. A flag here would leave the warning silent at that volume.
        it('counts every AI step, not just the first', () => {
            expect(
                countAiRunSteps({
                    actions: [
                        functionAction('template-posthog-create-task', 'task_1'),
                        functionAction('template-webhook', 'webhook_1'),
                        functionAction('template-posthog-run-scout', 'scout_1'),
                    ],
                })
            ).toBe(2)
        })

        it('is zero for a workflow with no steps', () => {
            expect(countAiRunSteps({ actions: [] })).toBe(0)
            expect(countAiRunSteps(null)).toBe(0)
        })
    })

    describe('eventTriggerVolumeQuery', () => {
        it('counts the trigger events over the window the copy promises', () => {
            const query = eventTriggerVolumeQuery({
                events: [{ id: 'purchase', type: 'events' }],
                filter_test_accounts: true,
            })

            expect(query.dateRange?.date_from).toBe(`-${TRIGGER_VOLUME_DAYS}d`)
            // Ends yesterday, so the window is whole days only. An open end would add today's
            // partial day, which the daily average divides as though it were complete.
            expect(query.dateRange?.date_to).toBe('-1d')
            expect(query.interval).toBe('day')
            expect(query.filterTestAccounts).toBe(true)
            expect(JSON.stringify(query.properties)).toContain("event = 'purchase'")
        })
    })
})
