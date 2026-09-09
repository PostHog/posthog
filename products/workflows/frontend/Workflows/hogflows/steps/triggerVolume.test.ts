import { HogFlowAction } from '../types'
import {
    DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY,
    TRIGGER_VOLUME_DAYS,
    countAiTaskSteps,
    countScoutSteps,
    eventTriggerVolumeFilters,
    eventTriggerVolumeQuery,
    exceedsAiTaskLimit,
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

    describe('step counts', () => {
        // A scout run goes to its own endpoint with its own throttle, so counting it against the
        // task cap would warn a scout-only workflow about a limit it never reaches.
        it.each([
            ['an AI task step', 'template-posthog-create-task', 1, 0],
            ['a scout step', 'template-posthog-run-scout', 0, 1],
            ['a webhook step', 'template-webhook', 0, 0],
        ])('%s', (_name, templateId, tasks, scouts) => {
            const workflow = { actions: [functionAction(templateId as string)] }

            expect(countAiTaskSteps(workflow)).toBe(tasks)
            expect(countScoutSteps(workflow)).toBe(scouts)
        })

        // Each step a run reaches creates its own task, so two steps reach the daily cap at half
        // the runs. A flag here would leave the warning silent at that volume.
        it('counts every task step, not just the first', () => {
            expect(
                countAiTaskSteps({
                    actions: [
                        functionAction('template-posthog-create-task', 'task_1'),
                        functionAction('template-webhook', 'webhook_1'),
                        functionAction('template-posthog-create-task', 'task_2'),
                    ],
                })
            ).toBe(2)
        })

        it('is zero for a workflow with no steps', () => {
            expect(countAiTaskSteps({ actions: [] })).toBe(0)
            expect(countAiTaskSteps(null)).toBe(0)
            expect(countScoutSteps(null)).toBe(0)
        })
    })

    describe('exceedsAiTaskLimit', () => {
        const cap = DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY

        it.each([
            // The backend counts tasks over a trailing 24 hours, so one busy day breaches the cap
            // even when the weekly average sits far below it.
            ['a burst day above the cap', cap * 5, 1, true],
            // Two steps double the tasks per run, so half the runs reach the same cap.
            ['half the runs with two task steps', cap * 0.6, 2, true],
            ['a quiet trigger', cap - 10, 1, false],
            ['a workflow with no task step', cap * 50, 0, false],
        ])('%s', (_name, peakPerDay, taskSteps, expected) => {
            expect(exceedsAiTaskLimit(peakPerDay as number, taskSteps as number)).toBe(expected)
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
