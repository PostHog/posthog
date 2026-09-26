import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, useValues } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { mswServer } from '~/mocks/jest'
import { mocksToHandlers } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepFunctionNode } from './hogFunctionStepLogic'
import { StepFunctionConfiguration } from './StepFunction'

type StepAction = StepFunctionNode['data']
type SavedWorkflowBody = Partial<HogFlow> & { stage_draft?: boolean }

const WORKFLOW_ID = 'wf-template-link-1'
const STEP_ID = 'email_node'
const LOGIC_PROPS: WorkflowLogicProps = { id: WORKFLOW_ID }

const makeLibraryTemplate = (id: string, name: string, subject: string): MessageTemplate => ({
    id,
    name,
    description: '',
    content: {
        templating: 'liquid',
        email: { from: '', to: '', subject, html: `<p>${subject}</p>`, text: subject, design: null },
    },
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    created_by: null,
})

const SPRING_TEMPLATE = makeLibraryTemplate(
    '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
    'Spring newsletter',
    'Spring update'
)
const SUMMER_TEMPLATE = makeLibraryTemplate(
    '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a6c',
    'Summer newsletter',
    'Summer update'
)

const emailStep = {
    id: STEP_ID,
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
} as StepAction

// A generic destination step whose template happens to have an email input, e.g. Mailgun.
const destinationStep = {
    id: STEP_ID,
    type: 'function',
    name: 'Send with a destination',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        template_id: 'template-destination-email',
        inputs: { template: { value: { to: 'recipient@example.com', subject: '', html: '' } } },
    },
} as StepAction

const hogFunctionTemplates = {
    results: [
        {
            id: 'template-email',
            name: 'Email',
            type: 'destination',
            status: 'hidden',
            free: false,
            inputs_schema: [{ type: 'native_email', key: 'email', label: 'Email message', required: true }],
        },
        {
            id: 'template-destination-email',
            name: 'Destination email',
            type: 'destination',
            status: 'stable',
            free: false,
            inputs_schema: [{ type: 'email', key: 'template', label: 'Email template', required: true }],
        },
    ],
    count: 2,
}

const makeWorkflow = (status: HogFlow['status'], step: StepAction): HogFlow => ({
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
        step,
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
        { from: 'trigger_node', to: STEP_ID, type: 'continue' },
        { from: STEP_ID, to: 'exit_node', type: 'continue' },
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

// The editor panel hands the step its node from the live workflow, so edits flow back into it.
function LiveStep(): JSX.Element {
    const { workflow } = useValues(workflowLogic)
    const action = workflow.actions.find((a) => a.id === STEP_ID) as StepAction
    return (
        <StepFunctionConfiguration node={{ id: STEP_ID, data: action, position: { x: 0, y: 0 } } as StepFunctionNode} />
    )
}

async function renderStep(
    status: HogFlow['status'],
    step: StepAction
): Promise<{ logic: ReturnType<typeof workflowLogic.build>; savedBodies: SavedWorkflowBody[] }> {
    const savedBodies: SavedWorkflowBody[] = []
    const workflow = makeWorkflow(status, step)
    mswServer.use(
        ...mocksToHandlers({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': workflow,
                '/api/projects/:team_id/hog_function_templates/': hogFunctionTemplates,
                '/api/environments/:team_id/messaging_templates/': {
                    results: [SPRING_TEMPLATE, SUMMER_TEMPLATE],
                    count: 2,
                },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    const body = (await request.json()) as SavedWorkflowBody
                    savedBodies.push(body)
                    return [200, { ...workflow, ...body }]
                },
                // The first save marks onboarding tasks complete on the team.
                '/api/projects/:team_id/': MOCK_DEFAULT_TEAM,
            },
        })
    )
    initKeaTests()
    // The email editor reads preflight on render, so let the common logics finish loading it first.
    await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
    const logic = workflowLogic(LOGIC_PROPS)
    logic.mount()
    await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess', 'loadHogFunctionTemplatesByIdSuccess'])
    // The test triggers the one save it inspects, so auto-save can't race it.
    logic.actions.setAutoSaveEnabled(false)

    render(
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <LiveStep />
        </BindLogic>
    )
    // The step's first read of the lazy-loaded hog function templates reloads them, and the step
    // shows a spinner until they land, so wait for that before touching the email editor.
    await expectLogic(logic).toDispatchActions(['loadHogFunctionTemplatesByIdSuccess'])
    return { logic, savedBodies }
}

async function pickLibraryTemplate(template: MessageTemplate): Promise<void> {
    fireEvent.click(await screen.findByText(template.name))
}

function stepConfig(logic: ReturnType<typeof workflowLogic.build>): Record<string, any> {
    return (logic.values.workflow.actions.find((a) => a.id === STEP_ID) as StepAction).config
}

describe('StepFunctionConfiguration', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a draft workflow', 'draft' as const, false],
        ['an active workflow, staged into its draft', 'active' as const, true],
    ])(
        'links an email step to the Library template inserted into it, keeps the link through a later edit, and saves it for %s',
        async (_label, status, expectStagedDraft) => {
            const { logic, savedBodies } = await renderStep(status, emailStep)

            fireEvent.click(await screen.findByText('Start from template'))
            await pickLibraryTemplate(SPRING_TEMPLATE)

            await waitFor(() => expect(stepConfig(logic).inputs.email.value.subject).toEqual('Spring update'))
            expect(stepConfig(logic).template_uuid).toEqual(SPRING_TEMPLATE.id)

            emailTemplaterLogic.findMounted()!.actions.setEmailTemplateValue('subject', 'Edited subject')
            await waitFor(() => expect(stepConfig(logic).inputs.email.value.subject).toEqual('Edited subject'))
            expect(stepConfig(logic).template_uuid).toEqual(SPRING_TEMPLATE.id)

            await expectLogic(logic, () => {
                logic.actions.saveWorkflow(logic.values.workflow)
            }).toDispatchActions(['saveWorkflowSuccess'])
            await expectLogic(teamLogic).toFinishAllListeners()

            expect(savedBodies).toHaveLength(1)
            const savedStep = savedBodies[0].actions?.find((a: HogFlowAction) => a.id === STEP_ID) as StepAction
            expect(savedStep.config.template_uuid).toEqual(SPRING_TEMPLATE.id)
            expect(savedStep.config.inputs.email.value.subject).toEqual('Edited subject')
            expect(savedBodies[0].stage_draft ?? false).toEqual(expectStagedDraft)

            logic.unmount()
        }
    )

    it('points the link at the latest Library template inserted into the email step', async () => {
        const { logic } = await renderStep('draft', emailStep)

        fireEvent.click(await screen.findByText('Start from template'))
        await pickLibraryTemplate(SPRING_TEMPLATE)
        await waitFor(() => expect(stepConfig(logic).template_uuid).toEqual(SPRING_TEMPLATE.id))
        // The picker unmounts after its close transition. Reopening it earlier makes react-modal
        // register the same instance twice.
        await waitFor(() => expect(screen.queryByText('Choose a starting point')).not.toBeInTheDocument())

        emailTemplaterLogic.findMounted()!.actions.setIsTemplatePickerOpen(true)
        await pickLibraryTemplate(SUMMER_TEMPLATE)

        await waitFor(() => expect(stepConfig(logic).inputs.email.value.subject).toEqual('Summer update'))
        expect(stepConfig(logic).template_uuid).toEqual(SUMMER_TEMPLATE.id)

        logic.unmount()
    })

    it('does not link a generic destination step that has an email input', async () => {
        const { logic } = await renderStep('draft', destinationStep)

        fireEvent.click(await screen.findByText('Start from template'))
        await pickLibraryTemplate(SPRING_TEMPLATE)

        await waitFor(() => expect(stepConfig(logic).inputs.template.value.subject).toEqual('Spring update'))
        expect(stepConfig(logic).template_uuid).toBeUndefined()

        logic.unmount()
    })
})
