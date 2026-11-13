import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Node } from '@xyflow/react'
import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import type { HogFlowAction } from '../../types'
import { getHogFlowStep } from '../HogFlowSteps'

interface MockCanvas {
    edit: (design: Record<string, any>) => void
}

const mockCanvases: MockCanvas[] = []

jest.mock('react-email-editor', () => {
    const React = jest.requireActual('react')
    return {
        __esModule: true,
        default: React.forwardRef(function FakeUnlayer({ onReady }: { onReady?: () => void }, ref: unknown) {
            const canvas = React.useMemo(() => {
                const listeners: Record<string, () => void> = {}
                let design: Record<string, any> | null = null
                const editor = {
                    loadDesign: (next: Record<string, any>) => {
                        design = next
                        listeners['design:loaded']?.()
                    },
                    addEventListener: (event: string, callback: () => void) => {
                        listeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) =>
                        callback({ html: `<p>${design?.body?.id}</p>`, design }),
                    exportPlainText: (callback: (data: any) => void) => callback({ text: String(design?.body?.id) }),
                    setMergeTags: () => {},
                    registerProvider: () => {},
                    registerCallback: () => {},
                }
                return {
                    editor,
                    edit: (next: Record<string, any>) => {
                        design = next
                        listeners['design:updated']?.()
                    },
                }
            }, [])
            React.useImperativeHandle(ref, () => ({ editor: canvas.editor }), [canvas])
            React.useEffect(() => {
                mockCanvases.push(canvas)
                onReady?.()
            }, [canvas]) // oxlint-disable-line react-hooks/exhaustive-deps
            return null
        }),
    }
})

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }
const STEP_ID = 'email_step'

const SANDBOX_STATUS = {
    integration_id: 11,
    from_address: 'sandbox@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const OWN_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'hello@example.com',
    config: { verified: true },
} as unknown as IntegrationType

const EMAIL_TEMPLATE = {
    id: 'template-email',
    name: 'Email',
    type: 'destination',
    status: 'hidden',
    free: false,
    inputs_schema: [{ type: 'native_email', key: 'email', label: 'Email message', required: true }],
}

const STORED_DESIGN = { body: { id: 'stored', rows: [{ id: 'r1' }] } }
const EDITED_DESIGN = { body: { id: 'edited', rows: [{ id: 'r2' }] } }

function ownStep(value: Record<string, any> = {}): HogFlowAction {
    return {
        id: STEP_ID,
        type: 'function_email',
        name: 'Welcome',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{ person.properties.email }}' },
                        subject: 'Hi',
                        html: '<p>stored</p>',
                        design: STORED_DESIGN,
                        from: { integrationId: 7 },
                        ...value,
                    },
                },
            },
        },
    } as HogFlowAction
}

const SANDBOX_STEP = {
    id: STEP_ID,
    type: 'email_sandbox',
    name: 'Welcome',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        inputs: {
            email: {
                templating: 'liquid',
                value: {
                    to: { email: '{{ person.properties.email }}' },
                    subject: 'Hi',
                    html: '<p>stored</p>',
                    design: STORED_DESIGN,
                },
            },
        },
    },
} as HogFlowAction

function storedStep(): HogFlowAction | undefined {
    return workflowLogic(LOGIC_PROPS).values.workflow.actions.find((action) => action.id === STEP_ID)
}

function StoredStepConfiguration(): JSX.Element | null {
    const { workflow, hogFunctionTemplatesById } = useValues(workflowLogic)
    const action = workflow.actions.find((candidate) => candidate.id === STEP_ID)
    if (!action) {
        return null
    }
    const node = { id: action.id, data: action, position: { x: 0, y: 0 } } as Node<HogFlowAction>
    return getHogFlowStep(action, hogFunctionTemplatesById)?.renderConfiguration(node) ?? null
}

async function renderStep(step: HogFlowAction): Promise<void> {
    const wfLogic = workflowLogic(LOGIC_PROPS)
    wfLogic.mount()
    await expectLogic(wfLogic).toDispatchActions(['loadHogFunctionTemplatesByIdSuccess'])
    wfLogic.actions.setWorkflowInfo({ actions: [...wfLogic.values.workflow.actions, step] })
    render(
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <StoredStepConfiguration />
        </BindLogic>
    )
    await screen.findByTestId('workflow-email-sender-select')
}

function openFromPicker(): HTMLElement {
    fireEvent.click(screen.getByTestId('workflow-email-sender-select'))
    const menu = document.querySelector<HTMLElement>('.Popover')
    if (!menu) {
        throw new Error('The From picker did not open')
    }
    return menu
}

async function editCanvasInTheOpenEditor(): Promise<void> {
    fireEvent.click(screen.getByText('Click to modify content'))
    await waitFor(() => expect(mockCanvases.length).toBeGreaterThan(0))
    mockCanvases[mockCanvases.length - 1].edit(EDITED_DESIGN)
}

function pickInTheOpenEditor(sender: string): void {
    const pickers = screen.getAllByTestId('workflow-email-sender-select')
    fireEvent.click(pickers[pickers.length - 1])
    const menus = document.querySelectorAll<HTMLElement>('.Popover')
    fireEvent.click(within(menus[menus.length - 1]).getByText(sender))
}

describe('SandboxSenderChoiceProvider', () => {
    beforeEach(() => {
        mockCanvases.length = 0
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates': { results: [EMAIL_TEMPLATE], count: 1 },
                '/api/projects/:team_id/integrations/': { results: [OWN_SENDER], next: null },
                '/api/projects/:team_id/workflow_email_sandbox/status/': SANDBOX_STATUS,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['Cancel', 'function_email'],
        ['Switch sender', 'email_sandbox'],
    ])(
        'asks before the From picker drops own-sender settings, and %s decides the step kind',
        async (decision, expected) => {
            await renderStep(ownStep({ replyTo: 'help@example.com' }))

            fireEvent.click(within(openFromPicker()).getByText('Sandbox sender'))
            fireEvent.click(await screen.findByText(decision))

            await waitFor(() => expect(storedStep()?.type).toEqual(expected))
        }
    )

    it.each<[string, HogFlowAction, string, string]>([
        ['an own step to the sandbox sender', ownStep(), 'Sandbox sender', 'email_sandbox'],
        ['a sandbox step to an own sender', SANDBOX_STEP, 'hello@example.com', 'function_email'],
    ])(
        'switches %s from the open editor, which stays open and keeps a canvas edit not yet exported',
        async (_, step, sender, expected) => {
            await renderStep(step)
            await editCanvasInTheOpenEditor()

            pickInTheOpenEditor(sender)

            await waitFor(() => expect(storedStep()?.type).toEqual(expected))
            expect(storedStep()?.config).toMatchObject({
                inputs: { email: { value: { design: EDITED_DESIGN, html: '<p>edited</p>' } } },
            })
            expect(router.values.searchParams.editor).toEqual('email')
            expect(screen.getByText('Done')).toBeInTheDocument()
        }
    )

    it('offers no sandbox sender when the project has not adopted it', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_email_sandbox/status/': { ...SANDBOX_STATUS, adoption_enabled: false },
            },
        })
        await renderStep(ownStep())

        expect(within(openFromPicker()).queryByText('Sandbox sender')).not.toBeInTheDocument()
    })
})
