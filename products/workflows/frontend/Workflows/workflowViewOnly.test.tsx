import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { HogFlowEventFilters } from './hogflows/filters/HogFlowFilters'
import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { HogFlowEditorPanelBuildDetail } from './hogflows/panel/HogFlowEditorPanelBuildDetail'
import { ViewOnlyArea } from './hogflows/panel/ViewOnlyArea'
import * as hogFlowSteps from './hogflows/steps/HogFlowSteps'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowViewOnlyBanner } from './WorkflowViewOnlyBanner'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(() => Promise.resolve(true)),
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

        fireEvent.click(screen.getByRole('button', { name: 'Show filters' }))

        expect(screen.getByText(/Firefox/)).toBeInTheDocument()
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
        ['tabs onward', { key: 'Tab' }],
    ])('lets a viewer who %s read a step field', (_, keyPress) => {
        renderForViewer(
            <ViewOnlyArea>
                <input aria-label="Subject" />
            </ViewOnlyArea>
        )

        expect(fireEvent.keyDown(screen.getByLabelText('Subject'), keyPress)).toBe(true)
    })

    it('lets a viewer copy a webhook URL from a step', () => {
        renderForViewer(
            <ViewOnlyArea>
                <CodeSnippet thing="Webhook URL">https://hooks.example.com/workflows/abc</CodeSnippet>
            </ViewOnlyArea>
        )

        fireEvent.click(document.querySelector<HTMLElement>('[data-attr="copy-code-button"]')!)

        expect(copyToClipboard).toHaveBeenCalledWith('https://hooks.example.com/workflows/abc', 'Webhook URL')
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

    it('lets a viewer copy the error details of a step that fails to render', () => {
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

        expect(copyToClipboard).toHaveBeenCalledWith(
            expect.stringContaining('Step settings failed to render'),
            'error details'
        )
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
})
