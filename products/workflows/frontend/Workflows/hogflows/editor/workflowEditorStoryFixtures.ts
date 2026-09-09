import { mswDecorator } from '~/mocks/browser'

import { NEW_WORKFLOW } from '../../workflowLogic'
import { EXAMPLE_WORKFLOWS } from '../tree/exampleWorkflows'
import type { HogFlow, HogFlowAction } from '../types'

export const CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID = 'storybook-complex-workflow'
export const CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW: HogFlow = {
    id: CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID,
    team_id: 1,
    version: 7,
    name: 'Customer onboarding and retention',
    description: 'Routes new accounts by stage and follows up when activation stalls.',
    status: 'draft',
    trigger: {
        type: 'event',
        filters: {
            events: [{ id: 'account_created', name: 'Account created', type: 'events' }],
            properties: [],
            actions: [],
        },
    },
    conversion: { window_minutes: 10080, filters: [] },
    exit_condition: 'exit_only_at_end',
    variables: [
        { key: 'account_stage', type: 'string', label: 'Account stage', default: 'new' },
        { key: 'follow_up_count', type: 'number', label: 'Follow-up count', default: 0 },
    ],
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'Account created',
            description: 'Starts when a new account is created.',
            config: {
                type: 'event',
                filters: {
                    events: [{ id: 'account_created', name: 'Account created', type: 'events' }],
                    properties: [],
                    actions: [],
                },
            },
        },
        {
            id: 'route-by-stage',
            type: 'conditional_branch',
            name: 'Route by customer stage',
            description: 'Choose a path based on the current account stage.',
            config: {
                conditions: [
                    {
                        name: 'Paid account',
                        filters: {
                            properties: [{ key: 'account_stage', value: ['paid'], operator: 'exact', type: 'person' }],
                        },
                    },
                    {
                        name: 'Trial account',
                        filters: {
                            properties: [{ key: 'account_stage', value: ['trial'], operator: 'exact', type: 'person' }],
                        },
                    },
                    {
                        name: 'At-risk account',
                        filters: {
                            properties: [
                                { key: 'account_stage', value: ['at_risk'], operator: 'exact', type: 'person' },
                            ],
                        },
                    },
                ],
            },
        },
        {
            id: 'notify-account-team',
            type: 'function',
            name: 'Notify account team',
            description: 'Send the paid account to the account team.',
            config: {
                template_id: 'template-slack',
                inputs: {
                    slack_workspace: { value: 1 },
                    channel: { value: '#account-updates' },
                    text: { value: 'A paid account was created for {person.properties.email}.', templating: 'hog' },
                },
            },
        },
        {
            id: 'wait-for-business-hours',
            type: 'wait_until_time_window',
            name: 'Wait for business hours',
            description: 'Continue on a weekday between 09:00 and 17:00 UTC.',
            config: { timezone: 'UTC', day: 'weekday', time: ['09:00', '17:00'] },
        },
        {
            id: 'choose-onboarding-path',
            type: 'random_cohort_branch',
            name: 'Choose onboarding path',
            description: 'Split trial accounts between two onboarding paths.',
            config: {
                cohorts: [
                    { name: 'Guided onboarding', percentage: 60 },
                    { name: 'Self-serve onboarding', percentage: 30 },
                ],
            },
        },
        {
            id: 'create-onboarding-task',
            type: 'function',
            name: 'Create onboarding task',
            description: 'Create a task for the guided onboarding path.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/onboarding' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', path: 'guided' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'wait-one-day',
            type: 'delay',
            name: 'Wait one day',
            description: 'Give the self-serve path time to activate.',
            config: { delay_duration: '1d' },
        },
        {
            id: 'send-self-serve-reminder',
            type: 'function',
            name: 'Send self-serve reminder',
            description: 'Request a reminder from the messaging service.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/reminders' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', reminder: 'activation' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'hold-control-group',
            type: 'delay',
            name: 'Hold control group',
            description: 'Wait before measuring the control group.',
            config: { delay_duration: '3d' },
        },
        {
            id: 'wait-for-activation',
            type: 'wait_until_condition',
            name: 'Wait for activation',
            description: 'Continue when the account activates or after seven days.',
            config: {
                condition: {
                    name: 'Product activated',
                    filters: { events: [{ id: 'product_activated', name: 'Product activated', type: 'events' }] },
                },
                max_wait_duration: '7d',
            },
        },
        {
            id: 'share-activation',
            type: 'function',
            name: 'Share activation',
            description: 'Notify the retention team that activation completed.',
            config: {
                template_id: 'template-slack',
                inputs: {
                    slack_workspace: { value: 1 },
                    channel: { value: '#retention-updates' },
                    text: { value: 'Account {person.id} activated.', templating: 'hog' },
                },
            },
        },
        {
            id: 'create-follow-up-task',
            type: 'function',
            name: 'Create follow-up task',
            description: 'Create a task when activation does not complete.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/follow-up' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', reason: 'activation_timeout' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'send-activation-outcome',
            type: 'function',
            name: 'Send activation outcome',
            description: 'Record whether the account activated or needs a follow-up.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/activation-outcomes' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'record-self-serve-account',
            type: 'function',
            name: 'Record self-serve account',
            description: 'Record accounts that do not match a managed stage.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/self-serve' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', path: 'self_serve' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'pause-before-summary',
            type: 'delay',
            name: 'Pause before summary',
            description: 'Wait 30 seconds before recording the final outcome.',
            config: { delay_duration: '30s' },
        },
        {
            id: 'record-workflow-outcome',
            type: 'function',
            name: 'Record workflow outcome',
            description: 'Send the completed route to the example endpoint.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/outcomes' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', status: 'complete' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'exit',
            type: 'exit',
            name: 'End workflow',
            description: 'The account has completed its onboarding route.',
            config: { reason: 'Onboarding route completed' },
        },
    ] as HogFlowAction[],
    edges: [
        { from: 'trigger', to: 'route-by-stage', type: 'continue' },
        { from: 'route-by-stage', to: 'notify-account-team', type: 'branch', index: 0 },
        { from: 'notify-account-team', to: 'wait-for-business-hours', type: 'continue' },
        { from: 'wait-for-business-hours', to: 'pause-before-summary', type: 'continue' },
        { from: 'route-by-stage', to: 'choose-onboarding-path', type: 'branch', index: 1 },
        { from: 'choose-onboarding-path', to: 'create-onboarding-task', type: 'branch', index: 0 },
        { from: 'create-onboarding-task', to: 'pause-before-summary', type: 'continue' },
        { from: 'choose-onboarding-path', to: 'wait-one-day', type: 'branch', index: 1 },
        { from: 'wait-one-day', to: 'send-self-serve-reminder', type: 'continue' },
        { from: 'send-self-serve-reminder', to: 'pause-before-summary', type: 'continue' },
        { from: 'choose-onboarding-path', to: 'hold-control-group', type: 'continue' },
        { from: 'hold-control-group', to: 'pause-before-summary', type: 'continue' },
        { from: 'route-by-stage', to: 'wait-for-activation', type: 'branch', index: 2 },
        { from: 'wait-for-activation', to: 'share-activation', type: 'branch', index: 0 },
        { from: 'share-activation', to: 'send-activation-outcome', type: 'continue' },
        { from: 'wait-for-activation', to: 'create-follow-up-task', type: 'continue' },
        { from: 'create-follow-up-task', to: 'send-activation-outcome', type: 'continue' },
        { from: 'send-activation-outcome', to: 'pause-before-summary', type: 'continue' },
        { from: 'route-by-stage', to: 'record-self-serve-account', type: 'continue' },
        { from: 'record-self-serve-account', to: 'pause-before-summary', type: 'continue' },
        { from: 'pause-before-summary', to: 'record-workflow-outcome', type: 'continue' },
        { from: 'record-workflow-outcome', to: 'exit', type: 'continue' },
    ],
    created_at: '2026-09-04T12:00:00.000Z',
    updated_at: '2026-09-04T12:00:00.000Z',
}

const PICKABLE_WORKFLOWS: Record<string, HogFlow> = {
    [CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID]: CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW,
    ...EXAMPLE_WORKFLOWS,
}

export const workflowEditorStoryDecorator = mswDecorator({
    get: {
        // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
        '/api/environments/:team_id/hog_flows/:id/': ({ params }) => [
            200,
            PICKABLE_WORKFLOWS[String(params.id)] ?? CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW,
        ],
        // nosemgrep: no-environments-api-urls-frontend -- api.messaging has not migrated to generated project routes.
        '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
    },
    patch: {
        // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
        '/api/environments/:team_id/hog_flows/:id/': async ({ request, params }) => [
            200,
            {
                ...(PICKABLE_WORKFLOWS[String(params.id)] ?? CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW),
                ...((await request.json()) as Partial<HogFlow>),
                updated_at: '2026-09-04T12:01:00.000Z',
            },
        ],
    },
    post: {
        // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
        '/api/environments/:team_id/hog_flows/': async ({ request }) => [
            201,
            {
                ...NEW_WORKFLOW,
                ...((await request.json()) as Partial<HogFlow>),
                id: 'storybook-new-workflow',
                team_id: 1,
                created_at: '2026-09-04T12:01:00.000Z',
                updated_at: '2026-09-04T12:01:00.000Z',
            },
        ],
        // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
        '/api/environments/:team_id/hog_flows/user_blast_radius/': {
            affected: 240,
            total: 1200,
            limit: 100000,
            dedupe_key: null,
            confirm_token: 'storybook-confirm-token',
        },
    },
})
