import { FEATURE_FLAGS } from 'lib/constants'

import type { HogFunctionTemplateType } from '~/types'

import type { HogFlowAction } from './types'
import {
    customStepName,
    destinationSteps,
    StepCatalogContext,
    stepKindName,
    workflowStepSections,
} from './workflowStepCatalog'

const mainEnvironment = { id: 1, project_id: 1 }

const listed = (context: Partial<StepCatalogContext>): Record<string, string[]> =>
    Object.fromEntries(
        workflowStepSections({
            featureFlags: {},
            currentTeam: mainEnvironment,
            isRowScopedTrigger: false,
            ...context,
        }).map((section) => [section.title, section.steps.map((step) => step.name)])
    )

describe('workflowStepCatalog', () => {
    it('lists every step a workflow can always add, in the order the step picker shows them', () => {
        expect(listed({})).toEqual({
            Dispatch: ['Email', 'SMS', 'Slack', 'Webhook'],
            AI: ['Run scout', 'Replay Vision'],
            Delays: ['Delay', 'Time window', 'Wait until'],
            'Audience split': ['Conditional branch', 'Cohort branch'],
            'PostHog actions': ['Set variable', 'Capture event', 'Update person property', 'Set group property'],
            Support: ['Get ticket', 'Update ticket', 'Send message'],
        })
    })

    it.each([
        {
            name: 'adds the AI task and classify steps behind their flags',
            context: {
                featureFlags: {
                    [FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION]: true,
                    [FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION]: true,
                },
            },
            ai: ['Create AI task', 'Run scout', 'Classify with AI', 'Replay Vision'],
        },
        {
            name: 'leaves the main-environment steps out of another environment',
            context: {
                featureFlags: { [FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION]: true },
                currentTeam: { id: 2, project_id: 1 },
            },
            ai: ['Create AI task'],
        },
        {
            name: 'leaves the main-environment steps out while the team loads',
            context: { currentTeam: null },
            ai: undefined,
        },
    ])('$name', ({ context, ai }) => {
        expect(listed(context).AI).toEqual(ai)
    })

    it('offers no step that needs a person to a workflow that runs on warehouse rows', () => {
        const sections = listed({ isRowScopedTrigger: true })

        expect([sections.Delays, sections['Audience split']]).toEqual([
            ['Delay', 'Time window'],
            ['Conditional branch'],
        ])
    })

    it('keeps destinations that are already a step of their own out of the destination list', () => {
        const template = (id: string, name: string): HogFunctionTemplateType =>
            ({ id, name, type: 'destination', status: 'stable', description: '' }) as HogFunctionTemplateType

        const steps = destinationSteps([template('template-slack', 'Slack'), template('template-hubspot', 'HubSpot')])

        expect(steps.map((step) => step.name)).toEqual(['HubSpot'])
    })

    it.each([
        ['a conditional branch', { type: 'conditional_branch', config: {} }, 'Conditional branch'],
        ['a wait for a condition', { type: 'wait_until_condition', config: {} }, 'Wait until'],
        ['a Slack step', { type: 'function', config: { template_id: 'template-slack' } }, 'Slack'],
        [
            'a ticket reply',
            { type: 'function', config: { template_id: 'template-posthog-send-ticket-message' } },
            'Send message',
        ],
        [
            'a Replay Vision step',
            { type: 'function', config: { template_id: 'template-posthog-replay-vision' } },
            'Replay Vision',
        ],
        [
            'a destination it does not list',
            { type: 'function', config: { template_id: 'template-hubspot' } },
            undefined,
        ],
    ])('names %s the way the step picker does', (_, action, name) => {
        expect(stepKindName(action as HogFlowAction)).toBe(name)
    })

    it.each([
        ['keeps a name someone gave the step', 'Nudge trial users', [], 'Nudge trial users'],
        ['skips the name the step picker gave it', 'Delay', [], undefined],
        ['skips the name of the destination it runs', 'HubSpot', ['HubSpot'], undefined],
        ['skips a name the caption already shows', 'Wait 1 day', ['Wait 1 day'], undefined],
        ['skips an empty name', '  ', [], undefined],
    ])('%s', (_, name, shownElsewhere, expected) => {
        const action = { type: 'delay', name, config: { delay_duration: '1h' } } as HogFlowAction

        expect(customStepName(action, shownElsewhere)).toBe(expected)
    })
})
