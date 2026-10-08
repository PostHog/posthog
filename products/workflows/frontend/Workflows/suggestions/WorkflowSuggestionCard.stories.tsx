import type { Meta, StoryFn } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { WorkflowProposalApi } from '../../generated/api.schemas'
import type { HogFlow, HogFlowAction } from '../hogflows/types'
import { NEW_WORKFLOW } from '../workflowLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

const WORKFLOW_ID = 'storybook-suggestion-card'

function emailHtml(cta: string): string {
    return [
        '<!DOCTYPE html>',
        '<html>',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <style>',
        '    body { margin: 0; padding: 0; background-color: #f7f8f9; }',
        '    .container { max-width: 500px; margin: 0 auto; }',
        '    .button { display: inline-block; padding: 12px 24px; border-radius: 6px; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <table class="container" role="presentation" cellpadding="0" cellspacing="0" width="100%">',
        '    <tr>',
        '      <td style="padding: 24px; font-size: 24px; font-weight: 700;">',
        '        Your first week with Example',
        '      </td>',
        '    </tr>',
        '    <tr>',
        '      <td style="padding: 0 24px; font-size: 16px; line-height: 24px;">',
        '        You signed up a few days ago. Here are three things that teams set up first.',
        '      </td>',
        '    </tr>',
        '    <tr>',
        '      <td style="padding: 12px 24px;">',
        '        <ul>',
        '          <li>Invite your team</li>',
        '          <li>Connect a data source</li>',
        '          <li>Build your first report</li>',
        '        </ul>',
        '      </td>',
        '    </tr>',
        '    <tr>',
        '      <td align="center" style="padding: 24px;">',
        `        <a class="button" href="https://example.com/start" style="background-color: #f09a00; color: #151515;">${cta}</a>`,
        '      </td>',
        '    </tr>',
        '    <tr>',
        '      <td style="padding: 24px; font-size: 12px; color: #555555;">',
        '        You get this email because you signed up for Example. <a href="{{ unsubscribe_url }}">Unsubscribe</a>',
        '      </td>',
        '    </tr>',
        '  </table>',
        '</body>',
        '</html>',
    ].join('\n')
}

const LIVE_WORKFLOW: HogFlow = {
    ...NEW_WORKFLOW,
    id: WORKFLOW_ID,
    name: 'Onboarding series',
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'Signed up',
            description: '',
            config: {
                type: 'event',
                filters: { events: [{ id: 'signed_up', name: 'signed_up', type: 'events' }] },
            },
        },
        {
            id: 'wait',
            type: 'delay',
            name: 'Wait before the welcome email',
            description: '',
            config: { delay_duration: '1d' },
        },
        {
            id: 'email',
            type: 'function_email',
            name: 'Welcome email',
            description: '',
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '' },
                            from: { email: 'hello@example.com', name: 'Example' },
                            subject: 'Welcome to Example',
                            preheader: 'Three things to set up this week',
                            text: 'Hi there,\nHere are three things that teams set up first.\nThanks,\nThe Example team',
                            html: emailHtml('Run the play'),
                        },
                    },
                },
            },
        },
    ] as HogFlowAction[],
}

function emailPatch(value: Record<string, unknown>): Record<string, unknown> {
    return { id: 'email', config: { inputs: { email: { value } } } }
}

function proposal(overrides: Partial<WorkflowProposalApi>): WorkflowProposalApi {
    return {
        id: 'proposal-1',
        title: 'Make the call to action explicit',
        rationale: 'Many people open this email, but few click the button. The button text does not say where it goes.',
        content: {},
        evidence: {},
        step_id: 'email',
        base_version: 3,
        is_stale: false,
        status: 'suggested',
        source_id: null,
        created_at: '2026-10-01T09:00:00Z',
        resolved_at: null,
        resolved_by: null,
        applied_version: null,
        ...overrides,
    } as WorkflowProposalApi
}

const meta: Meta<typeof WorkflowSuggestionCard> = {
    title: 'Products/Workflows/Suggestions/Suggestion card',
    component: WorkflowSuggestionCard,
    // Monaco lays out the diff after the first paint, so a snapshot is not stable.
    tags: ['test-skip'],
    parameters: { layout: 'padded' },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': LIVE_WORKFLOW,
                '/api/projects/:team_id/hog_flows/:id/proposals/': { count: 0, results: [] },
                '/api/projects/:team_id/hog_flows/:id/optimization/': { enabled: true },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<{ proposal: WorkflowProposalApi }> = ({ proposal }) => (
    <div className="max-w-[60rem]">
        <WorkflowSuggestionCard id={WORKFLOW_ID} proposal={proposal} />
    </div>
)

export const EmailHtmlChange = Template.bind({})
EmailHtmlChange.args = {
    proposal: proposal({ content: { actions: [emailPatch({ html: emailHtml('Create your first report') })] } }),
}

export const EmailTextFields = Template.bind({})
EmailTextFields.args = {
    proposal: proposal({
        title: 'Shorten the subject and drop the preheader',
        rationale: 'Shorter subjects get more opens on mobile. The preheader repeats the subject.',
        content: {
            actions: [
                emailPatch({
                    subject: 'Set up Example in 5 minutes',
                    preheader: null,
                    text: 'Hi there,\nHere are three things that teams set up in their first week.\nThanks,\nThe Example team',
                }),
            ],
        },
    }),
}

export const TriggerAndDelay = Template.bind({})
TriggerAndDelay.args = {
    proposal: proposal({
        title: 'Wait longer and include invited users',
        rationale: 'Most people activate on their second day. Invited users never get this series.',
        step_id: null,
        content: {
            actions: [
                { id: 'wait', config: { delay_duration: '2d' } },
                {
                    id: 'trigger',
                    config: {
                        filters: {
                            events: [
                                { id: 'signed_up', name: 'signed_up', type: 'events' },
                                { id: 'invite_accepted', name: 'invite_accepted', type: 'events' },
                            ],
                        },
                    },
                },
            ],
        },
    }),
}

export const NewStep = Template.bind({})
NewStep.args = {
    proposal: proposal({
        title: 'Follow up with people who did not click',
        rationale: 'People who open but do not click get no second message.',
        step_id: null,
        content: {
            actions: [
                {
                    id: 'follow_up_email',
                    name: 'Follow-up email',
                    type: 'function_email',
                    config: {
                        inputs: {
                            email: {
                                value: {
                                    subject: 'Did you get a chance to look?',
                                    text: 'Hi again,\nYour workspace is ready when you are.\nThe Example team',
                                },
                            },
                        },
                    },
                },
            ],
        },
    }),
}
