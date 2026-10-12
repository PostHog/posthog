import type { HogFlow } from '../hogflows/types'
import { buildWorkflowOutline, listEmailSteps } from './workflowPreviewOutline'

const INDENT = ' '

const email = (
    id: string,
    name: string,
    subject: string,
    from: Record<string, unknown> = { email: 'team@example.com', name: 'Team' }
): Record<string, unknown> => ({
    id,
    name,
    type: 'function_email',
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: { subject, from, html: `<p>${subject}</p>` },
            },
        },
    },
})

const abTestWorkflow = {
    name: 'Onboarding drip',
    actions: [
        {
            id: 'trigger',
            name: 'Trigger',
            type: 'trigger',
            config: { type: 'event', filters: { events: [{ id: 'signed up', name: 'signed up', type: 'events' }] } },
        },
        {
            id: 'split',
            name: 'Split audience',
            type: 'random_cohort_branch',
            config: { cohorts: [{ percentage: 50, name: 'Folders first' }, { percentage: 50 }] },
        },
        email('folders_1', 'Welcome', 'Welcome to Hedgebox'),
        { id: 'wait', name: 'Wait', type: 'delay', config: { delay_duration: '2d' } },
        email('folders_2', 'Follow up', 'Your files, on every device'),
        email('sharing_1', 'Welcome', 'Share your first folder'),
        { id: 'exit', name: 'Exit', type: 'exit', config: {} },
    ],
    edges: [
        { from: 'trigger', to: 'split', type: 'continue' },
        { from: 'split', to: 'folders_1', type: 'branch', index: 0 },
        { from: 'split', to: 'sharing_1', type: 'branch', index: 1 },
        { from: 'split', to: 'exit', type: 'continue' },
        { from: 'folders_1', to: 'wait', type: 'continue' },
        { from: 'wait', to: 'folders_2', type: 'continue' },
        { from: 'folders_2', to: 'exit', type: 'continue' },
        { from: 'sharing_1', to: 'exit', type: 'continue' },
    ],
} as unknown as HogFlow

describe('workflowPreviewOutline', () => {
    it('outlines each branch of a split with its steps, skipping exits', () => {
        expect(buildWorkflowOutline(abTestWorkflow)).toEqual([
            '• Trigger: signed up',
            '• Split audience',
            `${INDENT}↳ Folders first (50%)`,
            `${INDENT}${INDENT}• Welcome: email "Welcome to Hedgebox"`,
            `${INDENT}${INDENT}• Wait: 2d`,
            `${INDENT}${INDENT}• Follow up: email "Your files, on every device"`,
            `${INDENT}↳ If cohort #2 matches (50%)`,
            `${INDENT}${INDENT}• Welcome: email "Share your first folder"`,
        ])
    })

    it('points at a step that an earlier branch already listed instead of repeating it', () => {
        const merging = {
            ...abTestWorkflow,
            edges: abTestWorkflow.edges.map((edge) => (edge.from === 'sharing_1' ? { ...edge, to: 'wait' } : edge)),
        } as HogFlow

        expect(buildWorkflowOutline(merging).slice(-2)).toEqual([
            `${INDENT}${INDENT}• Welcome: email "Share your first folder"`,
            `${INDENT}${INDENT}• Continues at "Wait"`,
        ])
    })

    it('lists email steps in the order the outline runs them', () => {
        expect(listEmailSteps(abTestWorkflow).map((step) => [step.actionId, step.subject])).toEqual([
            ['folders_1', 'Welcome to Hedgebox'],
            ['folders_2', 'Your files, on every device'],
            ['sharing_1', 'Share your first folder'],
        ])
    })

    it('names the trigger event by its id when the filter has no display name', () => {
        const unnamedTrigger = {
            ...abTestWorkflow,
            actions: abTestWorkflow.actions.map((action) =>
                action.type === 'trigger'
                    ? {
                          ...action,
                          config: { type: 'event', filters: { events: [{ id: 'purchase', type: 'events' }] } },
                      }
                    : action
            ),
        } as HogFlow

        expect(buildWorkflowOutline(unnamedTrigger)[0]).toEqual('• Trigger: purchase')
    })

    it.each([
        ['the connected sender', { integrationId: 7 }, 'Hedgebox team <hello@example.com>'],
        ['a blank sender override', { integrationId: 7, email: '', name: '' }, 'Hedgebox team <hello@example.com>'],
        ['an overridden sender name', { integrationId: 7, email: '', name: 'Support' }, 'Support <hello@example.com>'],
        ['a sender name without an address', { name: 'Support' }, 'Support'],
        ['a plain template string', '{{ person.properties.owner }}', '{{ person.properties.owner }}'],
    ])('shows %s as the email sender', (_name, from, expected) => {
        const workflow = {
            ...abTestWorkflow,
            actions: [abTestWorkflow.actions[0], email('mail', 'Welcome', 'Hi', from as Record<string, unknown>)],
            edges: [{ from: 'trigger', to: 'mail', type: 'continue' }],
        } as unknown as HogFlow

        expect(listEmailSteps(workflow, { 7: { name: 'Hedgebox team', email: 'hello@example.com' } })[0].from).toEqual(
            expected
        )
    })
})
