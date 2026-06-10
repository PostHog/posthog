import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-email-validation-1'
const EMAIL_NODE_ID = 'email_node'

const makeEmailAction = (fromValue: any): Extract<HogFlowAction, { type: 'function_email' }> => ({
    id: EMAIL_NODE_ID,
    type: 'function_email',
    name: 'Send email',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    to: { email: 'recipient@example.com' },
                    from: fromValue,
                    subject: 'Hello',
                    html: '<p>Hello</p>',
                    text: 'Hello',
                },
                templating: 'liquid',
            },
        },
    },
})

const makeWorkflow = (fromValue: any): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Email validation test',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        makeEmailAction(fromValue),
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [
        { from: 'trigger_node', to: EMAIL_NODE_ID, type: 'continue' },
        { from: EMAIL_NODE_ID, to: 'exit_node', type: 'continue' },
    ],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
})

// Hangs the templates fetch so `hogFunctionTemplatesByIdLoading` stays true and the
// function-action branch in `actionValidationErrorsById` doesn't clobber the email block.
const hangingTemplatesEndpoint = (): Promise<unknown> => new Promise(() => {})

// Matches the production template-email definition closely enough for validation:
// a single required `native_email` input. Used to reproduce the loaded-templates state.
const loadedTemplatesResponse = {
    results: [
        {
            id: 'template-email',
            name: 'Email',
            type: 'destination',
            status: 'hidden',
            free: false,
            inputs_schema: [
                {
                    type: 'native_email',
                    key: 'email',
                    label: 'Email message',
                    required: true,
                },
            ],
        },
    ],
    count: 1,
}

describe('workflowLogic email step "from" validation', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['"from" has no integrationId (no sender picked)', {}],
        ['"from" is completely missing', undefined],
    ])('flags the step as invalid when %s', async (_name, fromValue) => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow(fromValue),
                '/api/projects/:team_id/hog_function_templates/': hangingTemplatesEndpoint,
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.errors.email).toBe('Choose who to send this email from')
    })

    it('does not flag a "from" error when an integration sender has been picked', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({ integrationId: 42 }),
                '/api/projects/:team_id/hog_function_templates/': hangingTemplatesEndpoint,
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.errors.email).toBeUndefined()
        expect(result?.valid).toBe(true)
    })

    it('keeps the email-block error after templates load (function-action branch must not clobber it)', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({}),
                '/api/projects/:team_id/hog_function_templates/': loadedTemplatesResponse,
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess', 'loadHogFunctionTemplatesByIdSuccess'])

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.errors.email).toBe('Choose who to send this email from')
    })

    it('propagates the step error into workflowHasActionErrors', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({}),
                '/api/projects/:team_id/hog_function_templates/': hangingTemplatesEndpoint,
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        expect(logic.values.workflowHasActionErrors).toBe(true)
    })
})
