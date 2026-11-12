import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import {
    DataWarehouseColumnsHint,
    DataWarehouseColumnsHintProps,
} from 'lib/components/CyclotronJob/DataWarehouseColumnsHint'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { tileCanvasLogic } from './hogflows/editor/tile-canvas/tileCanvasLogic'
import { TileStepNode } from './hogflows/editor/tile-canvas/TileStepNode'
import { HogFlowEventFilters } from './hogflows/filters/HogFlowFilters'
import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { HogFlowEditorPanelBuildDetail } from './hogflows/panel/HogFlowEditorPanelBuildDetail'
import { ViewOnlyArea } from './hogflows/panel/ViewOnlyArea'
import { AiTaskInstructionsCompare } from './hogflows/steps/components/AiTaskInstructionsCompare'
import { ScheduleList } from './hogflows/steps/components/ScheduleList'
import * as hogFlowSteps from './hogflows/steps/HogFlowSteps'
import { HogFlow, HogFlowSchedule } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowViewOnlyBanner } from './WorkflowViewOnlyBanner'

jest.mock('./hogflows/steps/components/InstructionsDiff', () => ({
    InstructionsDiff: () => null,
}))

const WORKFLOW_ID = 'wf-view-only-1'

const VIEWER_WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Shared onboarding',
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
        {
            id: 'push_node',
            type: 'function_push',
            name: 'Push',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { template_id: 'template-native-push', inputs: {} },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'push_node', type: 'continue' }],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    user_access_level: AccessControlLevel.Viewer,
}

function setWorkflowResourceAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: {
            ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
            [AccessControlResourceType.Workflow]: level,
        },
    } as AppContext
}

function MonacoLikeEditor(): JSX.Element {
    const codeRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        const code = codeRef.current!
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Tab') {
                event.preventDefault()
                code.value = event.shiftKey ? code.value.replace(/^ {4}/, '') : `    ${code.value}`
            }
            if (event.key === 'f' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                code.dataset.findWidget = 'open'
            }
        }
        code.addEventListener('keydown', onKeyDown)
        return () => code.removeEventListener('keydown', onKeyDown)
    }, [])

    return (
        <div className="monaco-editor">
            <textarea ref={codeRef} aria-label="Code" defaultValue="    return event" />
        </div>
    )
}

function fakeClipboard(): () => Promise<string> {
    let copied = ''
    Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
            writeText: async (text: string): Promise<void> => {
                copied = text
            },
        },
    })
    return async () => {
        await waitFor(() => expect(copied).not.toBe(''))
        return copied
    }
}

function renderForViewer(children: JSX.Element): void {
    render(
        <Provider>
            <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                {children}
            </BindLogic>
        </Provider>
    )
}

describe('view-only workflow', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': VIEWER_WORKFLOW,
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
    })

    afterEach(() => {
        cleanup()
        Reflect.deleteProperty(navigator, 'clipboard')
        logic?.unmount()
    })

    it('lets a viewer open nested sections of a step', () => {
        renderForViewer(
            <ViewOnlyArea>
                <LemonCollapse
                    panels={[{ key: 'ios', header: 'iOS options', content: <input aria-label="Sound" /> }]}
                />
            </ViewOnlyArea>
        )

        const header = screen.getByText('iOS options').closest('button')
        expect(header).toBeEnabled()
        fireEvent.click(header!)

        expect(screen.getByLabelText('Sound')).toBeInTheDocument()
    })

    it("lets a viewer go from a step's output variables to all workflow variables", () => {
        const editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })
        editorLogic.mount()
        editorLogic.actions.setSelectedNodeId('push_node')

        renderForViewer(
            <BindLogic logic={hogFlowEditorLogic} props={{ id: WORKFLOW_ID }}>
                <HogFlowEditorPanelBuildDetail />
            </BindLogic>
        )
        fireEvent.click(screen.getByText('Output variables'))
        fireEvent.click(screen.getByText('View all workflow variables'))

        expect(editorLogic.values.mode).toBe('variables')
        editorLogic.unmount()
    })

    it('lets a viewer show the property filters of a trigger event', () => {
        renderForViewer(
            <ViewOnlyArea>
                <HogFlowEventFilters
                    filtersKey="view-only-trigger"
                    filters={{
                        events: [
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                                properties: [{ key: '$browser', value: ['Firefox'], operator: 'exact', type: 'event' }],
                            },
                        ],
                    }}
                    setFilters={jest.fn()}
                />
            </ViewOnlyArea>
        )
        expect(screen.queryByText(/Firefox/)).not.toBeInTheDocument()

        fireEvent.click(document.querySelector('[data-attr="show-prop-filter-0"]')!)

        expect(screen.getByText(/Firefox/)).toBeInTheDocument()
    })

    it('lets a viewer pick another schedule to inspect', () => {
        const schedule = (id: string, rrule: string): HogFlowSchedule =>
            ({ id, rrule, starts_at: '2026-05-01T09:00:00.000Z', timezone: 'UTC' }) as HogFlowSchedule
        logic.actions.setSchedules([schedule('daily', 'FREQ=DAILY'), schedule('weekly', 'FREQ=WEEKLY')])
        renderForViewer(
            <ViewOnlyArea>
                <ScheduleList />
            </ViewOnlyArea>
        )

        fireEvent.click(document.querySelectorAll('[data-attr="workflow-schedule-row"]')[1])

        expect(logic.values.currentSchedule?.id).toBe('weekly')
    })

    it('lets a viewer copy a warehouse column reference', async () => {
        const copiedText = fakeClipboard()
        renderForViewer(
            <ViewOnlyArea>
                <DataWarehouseColumnsHint
                    schemaColumns={[
                        { name: 'email', type: 'string' } as DataWarehouseColumnsHintProps['schemaColumns'][0],
                    ]}
                />
            </ViewOnlyArea>
        )

        fireEvent.click(screen.getByText('Reference table columns'))
        fireEvent.click(screen.getByText('email'))

        expect(await copiedText()).toBe('{record.email}')
    })

    it('lets a viewer compare AI task instructions with another version', async () => {
        const aiTask = (prompt: string): HogFlow['actions'][number] => ({
            id: 'task_node',
            type: 'function',
            name: 'Create task',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { template_id: 'template-posthog-create-task', inputs: { prompt: { value: prompt } } },
        })
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': {
                    ...VIEWER_WORKFLOW,
                    status: 'active',
                    version: 3,
                    actions: [...VIEWER_WORKFLOW.actions, aiTask('Summarize the week')],
                },
                '/api/environments/:team_id/hog_flows/:id/revisions/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [2, 1].map((version) => ({
                        version,
                        created_at: '2026-09-01T10:00:00Z',
                        created_by: null,
                    })),
                },
                '/api/environments/:team_id/hog_flows/:id/revisions/:version/': (req) => [
                    200,
                    {
                        version: Number(req.params.version),
                        created_at: '2026-09-01T10:00:00Z',
                        created_by: null,
                        content: { actions: [aiTask(`Summarize version ${req.params.version}`)] },
                    },
                ],
            },
        })
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
        renderForViewer(
            <ViewOnlyArea>
                <AiTaskInstructionsCompare actionId="task_node" />
            </ViewOnlyArea>
        )

        fireEvent.click(screen.getByText('Compare instructions with another version'))
        expect(
            await screen.findByText('Removed lines are from v2. Added lines are in this step now.')
        ).toBeInTheDocument()
        fireEvent.click(screen.getByLabelText('Version to compare with'))
        fireEvent.click(await screen.findByText(/^v1 ·/))

        expect(
            await screen.findByText('Removed lines are from v1. Added lines are in this step now.')
        ).toBeInTheDocument()
        fireEvent.click(screen.getByText('Close'))
        expect(screen.getByText('Compare instructions with another version')).toBeInTheDocument()
    })

    it.each([
        ['clicks a button', 'Save as team default', (el: HTMLElement): boolean => fireEvent.click(el)],
        [
            'presses Enter on a button',
            'Save as team default',
            (el: HTMLElement) => fireEvent.keyDown(el, { key: 'Enter' }),
        ],
        ['types into a field', 'Subject', (el: HTMLElement): boolean => fireEvent.keyDown(el, { key: 'a' })],
        ['pastes into a field', 'Subject', (el: HTMLElement): boolean => fireEvent.paste(el)],
        ['cuts from a field', 'Subject', (el: HTMLElement): boolean => fireEvent.cut(el)],
        ['opens the context menu on a field', 'Subject', (el: HTMLElement): boolean => fireEvent.contextMenu(el)],
        [
            'deletes from a field through the context menu',
            'Subject',
            (el: HTMLElement): boolean =>
                fireEvent(
                    el,
                    new InputEvent('beforeinput', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'deleteContentBackward',
                    })
                ),
        ],
        ['steps a number field', 'Maximum emails', (el: HTMLElement) => fireEvent.keyDown(el, { key: 'ArrowUp' })],
        [
            'moves a code line up',
            'Code',
            (el: HTMLElement): boolean => fireEvent.keyDown(el, { key: 'ArrowUp', altKey: true }),
        ],
        [
            'copies a code line down',
            'Code',
            (el: HTMLElement): boolean => fireEvent.keyDown(el, { key: 'ArrowDown', altKey: true, shiftKey: true }),
        ],
        [
            'toggles a block comment in code',
            'Code',
            (el: HTMLElement): boolean => fireEvent.keyDown(el, { key: 'A', ctrlKey: true, shiftKey: true }),
        ],
    ])('stops a viewer who %s inside a step', (_, label, interact) => {
        const onEdit = jest.fn()
        renderForViewer(
            <ViewOnlyArea>
                <button aria-label="Save as team default" onClick={onEdit} onKeyDown={onEdit} />
                <input aria-label="Subject" onKeyDown={onEdit} onPaste={onEdit} onCut={onEdit} />
                <input aria-label="Maximum emails" type="number" onKeyDown={onEdit} />
                <div className="monaco-editor">
                    <textarea aria-label="Code" onKeyDown={onEdit} />
                </div>
            </ViewOnlyArea>
        )

        const reachedDefault = interact(screen.getByLabelText(label))

        expect(reachedDefault).toBe(false)
        expect(onEdit).not.toHaveBeenCalled()
    })

    it.each([
        ['copies', { key: 'c', ctrlKey: true }],
        ['selects all', { key: 'a', metaKey: true }],
        ['moves the cursor', { key: 'ArrowLeft' }],
        ['moves the cursor by word', { key: 'ArrowLeft', altKey: true }],
        ['selects by word', { key: 'ArrowRight', altKey: true, shiftKey: true }],
        ['moves by paragraph', { key: 'ArrowUp', altKey: true }],
        ['selects by paragraph', { key: 'ArrowDown', altKey: true, shiftKey: true }],
        ['tabs onward', { key: 'Tab' }],
        ['finds on the page', { key: 'f', ctrlKey: true }],
    ])('lets a viewer who %s read a step field', (_, keyPress) => {
        renderForViewer(
            <ViewOnlyArea>
                <input aria-label="Subject" />
            </ViewOnlyArea>
        )

        expect(fireEvent.keyDown(screen.getByLabelText('Subject'), keyPress)).toBe(true)
    })

    it.each([
        ['tabs out of a code editor instead of indenting', '{Tab}', 'After code'],
        ['shift-tabs out of a code editor instead of outdenting', '{Shift>}{Tab}{/Shift}', 'Before code'],
    ])('%s for a viewer', async (_, keys, nextFieldLabel) => {
        const user = userEvent.setup()
        renderForViewer(
            <ViewOnlyArea>
                <input aria-label="Before code" />
                <MonacoLikeEditor />
                <input aria-label="After code" />
            </ViewOnlyArea>
        )
        const code = screen.getByLabelText<HTMLTextAreaElement>('Code')
        code.focus()

        await user.keyboard(keys)

        expect(screen.getByLabelText(nextFieldLabel)).toHaveFocus()
        expect(code.value).toBe('    return event')
    })

    it('opens the browser find bar instead of the code editor find for a viewer', () => {
        renderForViewer(
            <ViewOnlyArea>
                <MonacoLikeEditor />
            </ViewOnlyArea>
        )
        const code = screen.getByLabelText('Code')

        const reachedBrowserFind = fireEvent.keyDown(code, { key: 'f', metaKey: true })

        expect(reachedBrowserFind).toBe(true)
        expect(code).not.toHaveAttribute('data-find-widget')
    })

    it('lets a viewer copy a webhook URL from a step', async () => {
        const copiedText = fakeClipboard()
        renderForViewer(
            <ViewOnlyArea>
                <CodeSnippet thing="Webhook URL">https://hooks.example.com/workflows/abc</CodeSnippet>
            </ViewOnlyArea>
        )

        fireEvent.click(document.querySelector<HTMLElement>('[data-attr="copy-code-button"]')!)

        expect(await copiedText()).toBe('https://hooks.example.com/workflows/abc')
    })

    it('shows a viewer the body of a plain-text email step', () => {
        renderForViewer(
            <ViewOnlyArea>
                <EmailTemplater
                    type="native_email"
                    value={{
                        design: null,
                        html: '',
                        text: 'Hi Ada, your order left the warehouse today.',
                        subject: 'Your order shipped',
                        from: '',
                        to: '',
                    }}
                    onChange={jest.fn()}
                />
            </ViewOnlyArea>
        )

        expect(screen.getByText('Hi Ada, your order left the warehouse today.')).toBeInTheDocument()
    })

    it('stops a viewer who toggles a push step setting', () => {
        const editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })
        editorLogic.mount()
        editorLogic.actions.setSelectedNodeId('push_node')

        renderForViewer(
            <BindLogic logic={hogFlowEditorLogic} props={{ id: WORKFLOW_ID }}>
                <HogFlowEditorPanelBuildDetail />
            </BindLogic>
        )
        const toggle = document.querySelector<HTMLElement>('[data-attr="workflow-push-sensitive-toggle"]')

        expect(fireEvent.click(toggle!)).toBe(false)
        editorLogic.unmount()
    })

    it('gives a viewer no step menu and no dragging on a canvas tile', () => {
        tileCanvasLogic({ id: WORKFLOW_ID }).mount()
        const workflow = logic.values.workflow

        renderForViewer(
            <BindLogic logic={tileCanvasLogic} props={{ id: WORKFLOW_ID }}>
                <TileStepNode action={workflow.actions[1]} workflow={workflow} count={undefined} />
            </BindLogic>
        )
        const tile = document.querySelector<HTMLElement>('[data-attr="workflow-tile-step"]')!

        expect(fireEvent.contextMenu(tile)).toBe(true)
        expect(tile).toHaveAttribute('draggable', 'false')
    })

    it('lets a viewer copy the error details of a step that fails to render', async () => {
        const copiedText = fakeClipboard()
        const FailingConfiguration = (): JSX.Element => {
            throw new Error('Step settings failed to render')
        }
        const realUseHogFlowStep = hogFlowSteps.useHogFlowStep
        jest.spyOn(hogFlowSteps, 'useHogFlowStep').mockImplementation((action) => {
            const step = realUseHogFlowStep(action)
            return step && { ...step, renderConfiguration: () => <FailingConfiguration /> }
        })
        jest.spyOn(console, 'error').mockImplementation(() => {})
        const editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })
        editorLogic.mount()
        editorLogic.actions.setSelectedNodeId('push_node')

        renderForViewer(
            <BindLogic logic={hogFlowEditorLogic} props={{ id: WORKFLOW_ID }}>
                <HogFlowEditorPanelBuildDetail />
            </BindLogic>
        )
        fireEvent.click(screen.getByText('Copy error details'))

        expect(await copiedText()).toContain('Step settings failed to render')
        editorLogic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        [AccessControlLevel.Editor, true],
        [AccessControlLevel.Viewer, false],
    ])('offers Duplicate to a viewer with %s access to workflows: %s', (resourceLevel, offersDuplicate) => {
        setWorkflowResourceAccess(resourceLevel)

        renderForViewer(<WorkflowViewOnlyBanner id={WORKFLOW_ID} />)

        expect(screen.getByText(/You can view this workflow but not edit it/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflow-view-only-duplicate"]') !== null).toBe(offersDuplicate)
    })

    it('tells a viewer when Duplicate fails', async () => {
        setWorkflowResourceAccess(AccessControlLevel.Editor)
        useMocks({ post: { '/api/projects/:team_id/hog_flows/': () => [500, { detail: 'Server error' }] } })
        const toastError = jest.spyOn(lemonToast, 'error')

        renderForViewer(<WorkflowViewOnlyBanner id={WORKFLOW_ID} />)
        await act(async () => {
            fireEvent.click(document.querySelector('[data-attr="workflow-view-only-duplicate"]')!)
        })

        expect(toastError).toHaveBeenCalledWith('Could not duplicate the workflow. Please try again.')
        toastError.mockRestore()
    })
})
