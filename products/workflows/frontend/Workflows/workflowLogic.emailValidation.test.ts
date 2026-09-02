import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-email-validation-1'
const EMAIL_NODE_ID = 'email_node'
const ADDED_EMAIL_NODE_ID = 'email_node_2'

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

const SENDER_ERROR = 'Choose an email sender, or connect a new one'

describe('workflowLogic email step "from" validation', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['"from" has no integrationId (no sender picked)', {}],
        ['"from" is completely missing', undefined],
    ])('marks the step invalid but stays quiet before any save attempt when %s', async (_name, fromValue) => {
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
        // A freshly opened template step always lacks a sender; it must read as clean (no message)
        // while still being invalid so the node badge and enable-gate keep working.
        expect(result?.valid).toBe(false)
        expect(result?.emailErrors).toBeUndefined()
        expect(result?.errors.email).toBeUndefined()
    })

    it('reveals the field messages when enabling an invalid draft, while blocking the save itself', async () => {
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

        // The Enable button stays clickable on an invalid draft: the dispatch is what records the
        // attempt and reveals the messages, while the listener guard aborts the actual enable.
        await expectLogic(logic, () => {
            logic.actions.saveWorkflowPartial({ status: 'active' })
        }).toNotHaveDispatchedActions(['saveWorkflow'])

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.emailErrors?.from).toBe(SENDER_ERROR)
    })

    it('keeps an email step added after a save attempt quiet until the next attempt', async () => {
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

        logic.actions.saveWorkflowPartial({ status: 'active' })
        expect(logic.values.actionValidationErrorsById[EMAIL_NODE_ID]?.emailErrors?.from).toBe(SENDER_ERROR)

        const addedAction = { ...makeEmailAction({}), id: ADDED_EMAIL_NODE_ID, name: 'Send another email' }
        logic.actions.setWorkflowValues({ actions: [...logic.values.workflow.actions, addedAction] })

        // The new step is invalid from the start but must not yell until the user attempts a
        // save/enable with it in place.
        expect(logic.values.actionValidationErrorsById[ADDED_EMAIL_NODE_ID]?.valid).toBe(false)
        expect(logic.values.actionValidationErrorsById[ADDED_EMAIL_NODE_ID]?.emailErrors).toBeUndefined()
        expect(logic.values.actionValidationErrorsById[EMAIL_NODE_ID]?.emailErrors?.from).toBe(SENDER_ERROR)

        logic.actions.saveWorkflowPartial({ status: 'active' })
        expect(logic.values.actionValidationErrorsById[ADDED_EMAIL_NODE_ID]?.emailErrors?.from).toBe(SENDER_ERROR)
    })

    it('surfaces the softened sender message on its field once a save is attempted', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({}),
                '/api/projects/:team_id/hog_function_templates/': hangingTemplatesEndpoint,
            },
            patch: { '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({}) },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        logic.actions.submitWorkflow()

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.emailErrors?.from).toBe(SENDER_ERROR)
        // Still per-field, never joined into a single blob under the whole input.
        expect(result?.errors.email).toBeUndefined()
    })

    it.each([
        [
            'one sender with valid templated overrides',
            {
                integrationId: 42,
                email: '{{ event.properties.sender_email }}',
                name: 'Community team',
            },
        ],
        ['a sender rotation', { integrationId: 42, integrationIds: [42, 43, 44] }],
    ])('does not flag a "from" error when %s has been picked', async (_name, fromValue) => {
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
        expect(result?.emailErrors).toBeUndefined()
        expect(result?.valid).toBe(true)
    })

    it('flags a broken Liquid template in the custom sender fields once a save is attempted', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow({
                    integrationId: 42,
                    email: '{{ event.properties.sender',
                }),
                '/api/projects/:team_id/hog_function_templates/': hangingTemplatesEndpoint,
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        logic.actions.saveWorkflowPartial({ status: 'active' })

        const result = logic.values.actionValidationErrorsById[EMAIL_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.emailErrors?.from).toContain('Liquid template error')
    })

    it('keeps the step invalid after templates load (generic validator must not resurface a blob)', async () => {
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
        // The generic input validator also joins the sub-fields into `errors.email`; it must be
        // stripped so nothing renders under the whole input.
        expect(result?.errors.email).toBeUndefined()
    })

    it('propagates the step error into workflowHasActionErrors regardless of save attempts', async () => {
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
