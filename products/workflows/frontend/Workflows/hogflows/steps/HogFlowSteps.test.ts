import { HogFlowAction } from '../types'
import { getHogFlowStep } from './HogFlowSteps'

const action = (type: HogFlowAction['type'], config: unknown): HogFlowAction =>
    ({ id: type, type, name: type, description: '', config }) as HogFlowAction

const previewLabels = (workflowAction: HogFlowAction): string[] =>
    getHogFlowStep(workflowAction, {})?.previews.map(({ label }) => label) ?? []

describe('HogFlow step previews', () => {
    it.each([
        [
            action('trigger', {
                type: 'event',
                filters: { events: [{ id: '$pageview' }], properties: [{}, {}] },
            }),
            ['Event · $pageview · 2 filters'],
        ],
        [action('delay', { delay_duration: '2h' }), ['Wait for 2 hours']],
        [action('wait_until_condition', { max_wait_duration: '1d' }), ['Up to 1d']],
        [
            action('wait_until_time_window', {
                day: 'weekday',
                time: ['09:00', '17:00'],
                timezone: 'UTC',
            }),
            ['Wait until weekdays between 09:00 and 17:00 (UTC)'],
        ],
        [action('conditional_branch', { conditions: [{}, {}] }), ['2 conditions']],
        [action('random_cohort_branch', { cohorts: [{}] }), ['1 cohort']],
        [
            action('function', {
                template_id: 'template-webhook',
                inputs: { method: { value: 'post' }, url: { value: 'https://hooks.example.com/path' } },
            }),
            ['POST hooks.example.com'],
        ],
        [
            action('function_email', {
                inputs: { email: { value: { to: { email: 'person@example.com' } } } },
            }),
            ['To person@example.com'],
        ],
        [action('function_sms', { inputs: { phoneNumber: { value: '+15555550123' } } }), ['To +15555550123']],
        [action('function_push', { inputs: { title: { value: 'Welcome back' } } }), ['Welcome back']],
        [action('exit', {}), ['End workflow']],
    ])('derives preview labels from the action config', (workflowAction, expected) => {
        expect(previewLabels(workflowAction)).toEqual(expected)
    })
})
