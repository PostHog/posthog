import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import {
    DataWarehouseColumnsHint,
    DataWarehouseColumnsHintProps,
} from 'lib/components/CyclotronJob/DataWarehouseColumnsHint'
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

const CODE = '    return event\n    // sent'

function MonacoLikeEditor(): JSX.Element {
    const codeRef = useRef<HTMLTextAreaElement>(null)
    const [isFindOpen, setIsFindOpen] = useState(false)
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    useEffect(() => {
        const code = codeRef.current!
        const editLines = (event: KeyboardEvent, edit: (lines: string[]) => string[]): void => {
            event.preventDefault()
            code.value = edit(code.value.split('\n')).join('\n')
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const withCtrlOrCmd = event.metaKey || event.ctrlKey
            if (event.key === 'Tab') {
                editLines(event, ([first, ...rest]) => [
                    event.shiftKey ? first.replace(/^ {4}/, '') : `    ${first}`,
                    ...rest,
                ])
            } else if (event.altKey && event.shiftKey && event.key === 'ArrowDown') {
                editLines(event, (lines) => [...lines, lines[lines.length - 1]])
            } else if (event.altKey && event.key === 'ArrowUp') {
                editLines(event, ([first, second]) => [second, first])
            } else if (withCtrlOrCmd && event.shiftKey && event.key.toLowerCase() === 'a') {
                editLines(event, (lines) => ['/*', ...lines, '*/'])
            } else if (withCtrlOrCmd && event.key === 'f') {
                event.preventDefault()
                setIsFindOpen(true)
            }
        }
        const onContextMenu = (event: MouseEvent): void => {
            event.preventDefault()
            setIsMenuOpen(true)
        }
        const onPaste = (event: ClipboardEvent): void => {
            event.preventDefault()
            code.value += event.clipboardData?.getData('text/plain') ?? ''
        }
        const onCut = (event: ClipboardEvent): void => {
            event.preventDefault()
            code.value = ''
        }
        code.addEventListener('keydown', onKeyDown)
        code.addEventListener('contextmenu', onContextMenu)
        code.addEventListener('paste', onPaste)
        code.addEventListener('cut', onCut)
        return () => {
            code.removeEventListener('keydown', onKeyDown)
            code.removeEventListener('contextmenu', onContextMenu)
            code.removeEventListener('paste', onPaste)
            code.removeEventListener('cut', onCut)
        }
    }, [])

    return (
        <div className="monaco-editor">
            <textarea ref={codeRef} aria-label="Code" defaultValue={CODE} />
            {isFindOpen && <input aria-label="Find in code" />}
            {isMenuOpen && <div role="menu" aria-label="Code menu" />}
        </div>
    )
}

function StepSettings(): JSX.Element {
    const [isSaved, setIsSaved] = useState(false)

    return (
        <>
            <button onClick={() => setIsSaved(true)}>Save as team default</button>
            {isSaved && <span>Saved as team default</span>}
            <input aria-label="Subject" defaultValue="Welcome" />
            <input aria-label="Maximum emails" type="number" defaultValue="3" />
            <MonacoLikeEditor />
            <input aria-label="Next field" />
        </>
    )
}

const removeBrowserDefaults: (() => void)[] = []

function emulateBrowserDefault<K extends keyof WindowEventMap>(
    type: K,
    action: (event: WindowEventMap[K], target: HTMLInputElement) => void
): void {
    const listener = (event: WindowEventMap[K]): void => {
        queueMicrotask(() => {
            if (!event.defaultPrevented) {
                action(event, event.target as HTMLInputElement)
            }
        })
    }
    window.addEventListener(type, listener, true)
    removeBrowserDefaults.push(() => window.removeEventListener(type, listener, true))
}

interface ReadingDefaults {
    copied: string
    findOpened: boolean
}

function emulateReadingDefaults(): ReadingDefaults {
    const browser: ReadingDefaults = { copied: '', findOpened: false }
    emulateBrowserDefault('keydown', (event, field) => {
        const withCtrlOrCmd = event.ctrlKey || event.metaKey
        if (withCtrlOrCmd && event.key === 'c') {
            browser.copied = field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0)
        } else if (withCtrlOrCmd && event.key === 'f') {
            browser.findOpened = true
        } else if (event.altKey && event.shiftKey && ['ArrowRight', 'ArrowDown'].includes(event.key)) {
            field.setSelectionRange(field.selectionStart, field.value.length)
        } else if (event.altKey && event.key === 'ArrowUp') {
            field.setSelectionRange(0, 0)
        }
    })
    return browser
}

type StepEdit = (user: ReturnType<typeof userEvent.setup>) => Promise<unknown>

const subjectField = (): HTMLInputElement => screen.getByLabelText<HTMLInputElement>('Subject')
const codeField = (): HTMLTextAreaElement => screen.getByLabelText<HTMLTextAreaElement>('Code')
const isSaved = (): boolean => screen.queryByText('Saved as team default') !== null
const isSubjectEdited = (): boolean => subjectField().value !== 'Welcome'
const isCodeEdited = (): boolean => codeField().value !== CODE

async function pressInCode(user: ReturnType<typeof userEvent.setup>, keys: string): Promise<void> {
    codeField().focus()
    await user.keyboard(keys)
}

const STEP_EDITS: [string, StepEdit, () => boolean][] = [
    ['clicks a button', (user) => user.click(screen.getByText('Save as team default')), isSaved],
    [
        'presses Enter on a button',
        async (user) => {
            screen.getByText('Save as team default').focus()
            await user.keyboard('{Enter}')
        },
        isSaved,
    ],
    [
        'types into a field',
        async (user) => {
            subjectField().focus()
            await user.keyboard('!')
        },
        isSubjectEdited,
    ],
    [
        'pastes into code',
        async (user) => {
            codeField().focus()
            await user.paste('!')
        },
        isCodeEdited,
    ],
    [
        'cuts from code',
        async (user) => {
            await pressInCode(user, '{Control>}a{/Control}')
            await user.cut()
        },
        isCodeEdited,
    ],
    [
        "deletes from a field through the browser's menu",
        async () => {
            emulateBrowserDefault('beforeinput', (_, field) => {
                field.value = field.value.slice(0, -1)
            })
            fireEvent(
                subjectField(),
                new InputEvent('beforeinput', { bubbles: true, cancelable: true, inputType: 'deleteContentBackward' })
            )
            await act(async () => {})
        },
        isSubjectEdited,
    ],
    [
        'steps a number field',
        async (user) => {
            emulateBrowserDefault('keydown', (event, field) => event.key === 'ArrowUp' && field.stepUp())
            screen.getByLabelText('Maximum emails').focus()
            await user.keyboard('{ArrowUp}')
        },
        () => screen.getByLabelText<HTMLInputElement>('Maximum emails').value !== '3',
    ],
    [
        'opens the code menu',
        (user) => user.pointer({ keys: '[MouseRight]', target: codeField() }),
        () => screen.queryByLabelText('Code menu') !== null,
    ],
    ['moves a code line up', (user) => pressInCode(user, '{Alt>}{ArrowUp}{/Alt}'), isCodeEdited],
    ['copies a code line down', (user) => pressInCode(user, '{Alt>}{Shift>}{ArrowDown}{/Shift}{/Alt}'), isCodeEdited],
    [
        'toggles a block comment in code',
        (user) => pressInCode(user, '{Control>}{Shift>}A{/Shift}{/Control}'),
        isCodeEdited,
    ],
]

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
        removeBrowserDefaults.splice(0).forEach((remove) => remove())
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

    it.each<[string, AccessControlLevel, StepEdit, () => boolean, boolean]>(
        STEP_EDITS.flatMap(([action, edit, isEdited]) => [
            [`stops a viewer who ${action}`, AccessControlLevel.Viewer, edit, isEdited, false],
            [`lets an editor who ${action} change the step`, AccessControlLevel.Editor, edit, isEdited, true],
        ])
    )('%s', async (_, accessLevel, edit, isEdited, edited) => {
        logic.actions.loadWorkflowSuccess({ ...VIEWER_WORKFLOW, user_access_level: accessLevel })
        const user = userEvent.setup()
        renderForViewer(
            <ViewOnlyArea>
                <StepSettings />
            </ViewOnlyArea>
        )

        await edit(user)

        expect(isEdited()).toBe(edited)
    })

    it.each<
        [string, string, [number, number], (subject: HTMLInputElement, browser: ReadingDefaults) => unknown, unknown]
    >([
        ['copies the selection', '{Control>}c{/Control}', [0, 7], (_, browser) => browser.copied, 'Welcome'],
        [
            'selects all',
            '{Control>}a{/Control}',
            [3, 3],
            (subject) => [subject.selectionStart, subject.selectionEnd],
            [0, 7],
        ],
        ['moves the cursor', '{ArrowLeft}', [7, 7], (subject) => subject.selectionStart, 6],
        ['moves the cursor by word', '{Alt>}{ArrowLeft}{/Alt}', [7, 7], (subject) => subject.selectionStart, 6],
        ['selects by word', '{Alt>}{Shift>}{ArrowRight}{/Shift}{/Alt}', [0, 0], (subject) => subject.selectionEnd, 7],
        ['moves by paragraph', '{Alt>}{ArrowUp}{/Alt}', [7, 7], (subject) => subject.selectionStart, 0],
        [
            'selects by paragraph',
            '{Alt>}{Shift>}{ArrowDown}{/Shift}{/Alt}',
            [0, 0],
            (subject) => subject.selectionEnd,
            7,
        ],
        ['tabs onward', '{Tab}', [0, 0], () => document.activeElement?.getAttribute('aria-label'), 'Next field'],
        ['finds on the page', '{Control>}f{/Control}', [0, 0], (_, browser) => browser.findOpened, true],
    ])('lets a viewer who %s read a step field', async (_, keys, [selectionStart, selectionEnd], observe, expected) => {
        const user = userEvent.setup()
        renderForViewer(
            <ViewOnlyArea>
                <input aria-label="Subject" defaultValue="Welcome" />
                <input aria-label="Next field" />
            </ViewOnlyArea>
        )
        const browser = emulateReadingDefaults()
        const subject = screen.getByLabelText<HTMLInputElement>('Subject')
        subject.focus()
        subject.setSelectionRange(selectionStart, selectionEnd)

        await user.keyboard(keys)

        expect(observe(subject, browser)).toEqual(expected)
    })

    it.each([
        ['a viewer tabs out of a code editor', AccessControlLevel.Viewer, '{Tab}', 'After code', CODE],
        [
            'a viewer shift-tabs out of a code editor',
            AccessControlLevel.Viewer,
            '{Shift>}{Tab}{/Shift}',
            'Before code',
            CODE,
        ],
        ['an editor indents code with Tab', AccessControlLevel.Editor, '{Tab}', 'Code', `    ${CODE}`],
        [
            'an editor outdents code with Shift+Tab',
            AccessControlLevel.Editor,
            '{Shift>}{Tab}{/Shift}',
            'Code',
            CODE.slice(4),
        ],
    ])('%s', async (_, accessLevel, keys, focusedFieldLabel, codeAfter) => {
        logic.actions.loadWorkflowSuccess({ ...VIEWER_WORKFLOW, user_access_level: accessLevel })
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

        expect(screen.getByLabelText(focusedFieldLabel)).toHaveFocus()
        expect(code.value).toBe(codeAfter)
    })

    it.each([
        ['a viewer gets the browser find bar instead of the code editor find', AccessControlLevel.Viewer, true],
        ['an editor gets the code editor find', AccessControlLevel.Editor, false],
    ])('%s', async (_, accessLevel, getsBrowserFind) => {
        logic.actions.loadWorkflowSuccess({ ...VIEWER_WORKFLOW, user_access_level: accessLevel })
        const user = userEvent.setup()
        renderForViewer(
            <ViewOnlyArea>
                <MonacoLikeEditor />
            </ViewOnlyArea>
        )
        const browser = emulateReadingDefaults()
        screen.getByLabelText('Code').focus()

        await user.keyboard('{Control>}f{/Control}')

        expect(browser.findOpened).toBe(getsBrowserFind)
        expect(screen.queryByLabelText('Find in code') === null).toBe(getsBrowserFind)
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

    it.each([
        ['stops a viewer who toggles a push step setting', AccessControlLevel.Viewer, 'false'],
        ['lets an editor toggle a push step setting', AccessControlLevel.Editor, 'true'],
    ])('%s', async (_, accessLevel, checkedAfter) => {
        const savedWorkflow = async ({ request }: { request: Request }): Promise<[number, HogFlow]> => [
            200,
            { ...VIEWER_WORKFLOW, user_access_level: accessLevel, ...(await request.json()) },
        ]
        useMocks({
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': savedWorkflow,
                '/api/projects/:team_id/hog_flows/:id/': savedWorkflow,
            },
        })
        logic.actions.loadWorkflowSuccess({ ...VIEWER_WORKFLOW, user_access_level: accessLevel })
        const editorLogic = hogFlowEditorLogic({ id: WORKFLOW_ID })
        editorLogic.mount()
        editorLogic.actions.setSelectedNodeId('push_node')

        renderForViewer(
            <BindLogic logic={hogFlowEditorLogic} props={{ id: WORKFLOW_ID }}>
                <HogFlowEditorPanelBuildDetail />
            </BindLogic>
        )
        const toggle = document.querySelector<HTMLElement>('[data-attr="workflow-push-sensitive-toggle"]')!
        await userEvent.click(toggle)

        expect(toggle).toHaveAttribute('aria-checked', checkedAfter)
        editorLogic.unmount()
    })

    it.each([
        ['gives a viewer no step menu and no dragging on a canvas tile', AccessControlLevel.Viewer, false],
        ['gives an editor the step menu and dragging on a canvas tile', AccessControlLevel.Editor, true],
    ])('%s', async (_, accessLevel, canEditStep) => {
        const exit = {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        } as HogFlow['actions'][number]
        logic.actions.loadWorkflowSuccess({
            ...VIEWER_WORKFLOW,
            user_access_level: accessLevel,
            actions: [...VIEWER_WORKFLOW.actions, exit],
            edges: [...VIEWER_WORKFLOW.edges, { from: 'push_node', to: 'exit_node', type: 'continue' }],
        })
        tileCanvasLogic({ id: WORKFLOW_ID }).mount()
        const workflow = logic.values.workflow

        renderForViewer(
            <BindLogic logic={tileCanvasLogic} props={{ id: WORKFLOW_ID }}>
                <TileStepNode action={workflow.actions[1]} workflow={workflow} count={undefined} />
            </BindLogic>
        )
        const tile = document.querySelector<HTMLElement>('[data-attr="workflow-tile-step"]')!
        await userEvent.pointer({ keys: '[MouseRight]', target: tile })

        expect(document.querySelector('[data-attr="workflow-tile-step-delete"]') !== null).toBe(canEditStep)
        expect(tile).toHaveAttribute('draggable', String(canEditStep))
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
        const { ToastContainer } = jest.requireActual('react-toastify')
        setWorkflowResourceAccess(AccessControlLevel.Editor)
        useMocks({ post: { '/api/projects/:team_id/hog_flows/': () => [500, { detail: 'Server error' }] } })

        renderForViewer(
            <>
                <WorkflowViewOnlyBanner id={WORKFLOW_ID} />
                <ToastContainer />
            </>
        )
        fireEvent.click(document.querySelector('[data-attr="workflow-view-only-duplicate"]')!)

        expect(await screen.findByText('Could not duplicate the workflow. Please try again.')).toBeInTheDocument()
    })
})
