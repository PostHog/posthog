import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, useValues } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepFunctionNode } from './hogFunctionStepLogic'
import { StepFunctionConfiguration } from './StepFunction'

type EmailAction = Extract<HogFlowAction, { type: 'function_email' }>

const WORKFLOW_ID = 'wf-template-link-1'
const EMAIL_NODE_ID = 'email_node'
const LOGIC_PROPS: WorkflowLogicProps = { id: WORKFLOW_ID }

const LIBRARY_TEMPLATE: MessageTemplate = {
    id: '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
    name: 'Spring newsletter',
    description: '',
    content: {
        templating: 'liquid',
        email: {
            from: '',
            to: '',
            subject: 'Our spring update',
            html: '<p>Hello from the library</p>',
            text: 'Hello from the library',
            design: null,
        },
    },
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    created_by: null,
}

const emailAction: EmailAction = {
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
                value: { to: { email: 'recipient@example.com' }, from: { integrationId: 1 }, subject: '', html: '' },
                templating: 'liquid',
            },
        },
    },
}

const makeWorkflow = (status: HogFlow['status']): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Template link test',
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
        emailAction,
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
    status,
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
})

const emailHogFunctionTemplates = {
    results: [
        {
            id: 'template-email',
            name: 'Email',
            type: 'destination',
            status: 'hidden',
            free: false,
            inputs_schema: [{ type: 'native_email', key: 'email', label: 'Email message', required: true }],
        },
    ],
    count: 1,
}

// The editor panel hands the step its node from the live workflow, so edits flow back into it.
function LiveEmailStep(): JSX.Element {
    const { workflow } = useValues(workflowLogic)
    const action = workflow.actions.find((a) => a.id === EMAIL_NODE_ID) as EmailAction
    return (
        <StepFunctionConfiguration
            node={{ id: EMAIL_NODE_ID, data: action, position: { x: 0, y: 0 } } as StepFunctionNode}
        />
    )
}

describe('StepFunctionConfiguration', () => {
    let savedBodies: Record<string, any>[]

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a draft workflow', 'draft' as const, false],
        ['an active workflow, staged into its draft', 'active' as const, true],
    ])(
        'links an email step to the Library template inserted into it, keeps the link through a later edit, and saves it for %s',
        async (_label, status, expectStagedDraft) => {
            savedBodies = []
            const workflow = makeWorkflow(status)
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_flows/:id/': workflow,
                    '/api/projects/:team_id/hog_function_templates/': emailHogFunctionTemplates,
                    '/api/environments/:team_id/messaging_templates/': { results: [LIBRARY_TEMPLATE], count: 1 },
                },
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        savedBodies.push(body)
                        return [200, { ...workflow, ...body }]
                    },
                },
            })
            initKeaTests()
            preflightLogic.mount()
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            const logic = workflowLogic(LOGIC_PROPS)
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess', 'loadHogFunctionTemplatesByIdSuccess'])
            // The test triggers the one save it inspects, so auto-save can't race it.
            logic.actions.setAutoSaveEnabled(false)

            render(
                <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                    <LiveEmailStep />
                </BindLogic>
            )
            // The step's first read of the lazy-loaded hog function templates reloads them, and the
            // step shows a spinner until they land, so wait for that before touching the email editor.
            await expectLogic(logic).toDispatchActions(['loadHogFunctionTemplatesByIdSuccess'])

            fireEvent.click(await screen.findByText('Start from template'))
            fireEvent.click(await screen.findByText(LIBRARY_TEMPLATE.name))

            const emailStepConfig = (): EmailAction['config'] =>
                (logic.values.workflow.actions.find((a) => a.id === EMAIL_NODE_ID) as EmailAction).config

            await waitFor(() => expect(emailStepConfig().inputs.email.value.subject).toEqual('Our spring update'))
            expect(emailStepConfig().template_uuid).toEqual(LIBRARY_TEMPLATE.id)

            emailTemplaterLogic.findMounted()!.actions.setEmailTemplateValue('subject', 'Edited subject')
            await waitFor(() => expect(emailStepConfig().inputs.email.value.subject).toEqual('Edited subject'))
            expect(emailStepConfig().template_uuid).toEqual(LIBRARY_TEMPLATE.id)

            await expectLogic(logic, () => {
                logic.actions.saveWorkflow(logic.values.workflow)
            }).toDispatchActions(['saveWorkflowSuccess'])

            expect(savedBodies).toHaveLength(1)
            const savedEmailStep = savedBodies[0].actions.find((a: HogFlowAction) => a.id === EMAIL_NODE_ID)
            expect(savedEmailStep.config.template_uuid).toEqual(LIBRARY_TEMPLATE.id)
            expect(savedEmailStep.config.inputs.email.value.subject).toEqual('Edited subject')
            expect(savedBodies[0].stage_draft ?? false).toEqual(expectStagedDraft)

            logic.unmount()
        }
    )
})
