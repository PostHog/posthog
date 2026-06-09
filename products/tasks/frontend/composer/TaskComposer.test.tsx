import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { SessionConfigOption } from '../conversation/acp-types'

const sendMessageSpy = jest.fn()
const cancelRunSpy = jest.fn()
const setConfigOptionSpy = jest.fn()

const MODE_OPTION: SessionConfigOption = {
    type: 'select',
    id: 'mode',
    name: 'Mode',
    category: 'mode',
    currentValue: 'default',
    options: [
        { value: 'plan', name: 'Plan' },
        { value: 'default', name: 'Default' },
        { value: 'acceptEdits', name: 'Accept edits' },
    ],
}

const MODEL_OPTION: SessionConfigOption = {
    type: 'select',
    id: 'model',
    name: 'Model',
    category: 'model',
    currentValue: 'sonnet',
    options: [
        { value: 'opus', name: 'Opus' },
        { value: 'sonnet', name: 'Sonnet' },
    ],
}

const THOUGHT_OPTION: SessionConfigOption = {
    type: 'select',
    id: 'thought_level',
    name: 'Effort',
    category: 'thought_level',
    currentValue: 'medium',
    options: [
        { value: 'low', name: 'Low' },
        { value: 'medium', name: 'Medium' },
    ],
}

// A lightweight stand-in for the real logic that avoids the heavy connect()
// graph (taskDetailSceneLogic loaders, teamLogic, streaming) while exposing the
// exact actions/values the component reads.
const mockTaskComposerLogic = kea<mockTaskComposerLogicType>([
    path(['products', 'tasks', 'composer', 'mockTaskComposerLogic']),
    props({} as { taskId: string }),
    key((p: { taskId: string }) => p.taskId),
    actions({
        setDraft: (draft: string) => ({ draft }),
        addFiles: (files: File[]) => ({ files }),
        removeFile: (index: number) => ({ index }),
        sendMessage: true,
        cancelRun: true,
        setConfigOption: (configId: string, value: string) => ({ configId, value }),
        setPendingFiles: (files: File[]) => ({ files }),
        setConfigOptions: (configOptions: SessionConfigOption[]) => ({ configOptions }),
        setAgentBusy: (agentBusy: boolean) => ({ agentBusy }),
        setSandboxReady: (sandboxReady: boolean) => ({ sandboxReady }),
    }),
    reducers({
        draft: ['' as string, { setDraft: (_: string, { draft }: { draft: string }) => draft }],
        pendingFiles: [
            [] as File[],
            {
                setPendingFiles: (_: File[], { files }: { files: File[] }) => files,
                addFiles: (state: File[], { files }: { files: File[] }) => [...state, ...files],
                removeFile: (state: File[], { index }: { index: number }) => state.filter((_, i) => i !== index),
            },
        ],
        configOptions: [
            [] as SessionConfigOption[],
            {
                setConfigOptions: (
                    _: SessionConfigOption[],
                    { configOptions }: { configOptions: SessionConfigOption[] }
                ) => configOptions,
            },
        ],
        agentBusy: [false, { setAgentBusy: (_: boolean, { agentBusy }: { agentBusy: boolean }) => agentBusy }],
        sandboxReady: [
            true,
            { setSandboxReady: (_: boolean, { sandboxReady }: { sandboxReady: boolean }) => sandboxReady },
        ],
    }),
    selectors({
        taskId: [() => [(_: unknown, p: { taskId: string }) => p.taskId], (taskId: string) => taskId],
    }),
    listeners(() => ({
        sendMessage: () => sendMessageSpy(),
        cancelRun: () => cancelRunSpy(),
        setConfigOption: ({ configId, value }: { configId: string; value: string }) =>
            setConfigOptionSpy(configId, value),
    })),
])

jest.mock('./taskComposerLogic', () => ({
    taskComposerLogic: (p: { taskId: string }) => mockTaskComposerLogic(p),
}))

import { TaskComposer } from './TaskComposer'
import type { mockTaskComposerLogicType } from './TaskComposer.testType'

const TASK_ID = 'task-1'

function mountComposer(): ReturnType<typeof mockTaskComposerLogic.build> {
    const logic = mockTaskComposerLogic({ taskId: TASK_ID })
    logic.mount()
    act(() => {
        render(
            <Provider>
                <TaskComposer taskId={TASK_ID} />
            </Provider>
        )
    })
    return logic
}

function getTextarea(): HTMLTextAreaElement {
    return screen.getByRole('textbox') as HTMLTextAreaElement
}

function expectSendDisabled(disabled: boolean): void {
    expect(screen.getByLabelText('Send message')).toHaveAttribute('aria-disabled', String(disabled))
}

describe('TaskComposer', () => {
    let logic: ReturnType<typeof mockTaskComposerLogic.build>

    beforeEach(() => {
        initKeaTests()
        sendMessageSpy.mockClear()
        cancelRunSpy.mockClear()
        setConfigOptionSpy.mockClear()
        logic = mountComposer()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        jest.clearAllMocks()
    })

    it('renders the composer container and a textarea', () => {
        expect(screen.getByTestId('task-composer')).toBeInTheDocument()
        expect(getTextarea()).toBeInTheDocument()
    })

    it('shows the ready placeholder when the sandbox is ready', () => {
        expect(getTextarea()).toHaveAttribute('placeholder', 'Send a follow-up…')
    })

    it('shows the not-ready placeholder when the sandbox is not ready', () => {
        act(() => logic.actions.setSandboxReady(false))
        expect(getTextarea()).toHaveAttribute('placeholder', 'Message will be sent once the run starts…')
    })

    it('writes typed text into the draft via onChange', () => {
        fireEvent.change(getTextarea(), { target: { value: 'hello world' } })
        expect(logic.values.draft).toBe('hello world')
    })

    it('sends on plain Enter', () => {
        act(() => logic.actions.setDraft('do the thing'))
        fireEvent.keyDown(getTextarea(), { key: 'Enter' })
        expect(sendMessageSpy).toHaveBeenCalledTimes(1)
    })

    it('does not send on Shift+Enter (newline)', () => {
        act(() => logic.actions.setDraft('line one'))
        fireEvent.keyDown(getTextarea(), { key: 'Enter', shiftKey: true })
        expect(sendMessageSpy).not.toHaveBeenCalled()
    })

    it('sends when the send button is clicked with non-empty draft', () => {
        act(() => logic.actions.setDraft('a message'))
        fireEvent.click(screen.getByLabelText('Send message'))
        expect(sendMessageSpy).toHaveBeenCalledTimes(1)
    })

    it('disables the send button when the draft is empty and there are no files', () => {
        expect(logic.values.draft).toBe('')
        expect(logic.values.pendingFiles).toHaveLength(0)
        expectSendDisabled(true)
    })

    it('enables the send button when the draft has content', () => {
        act(() => logic.actions.setDraft('ready to send'))
        expectSendDisabled(false)
    })

    it('treats a whitespace-only draft as empty for send-enablement', () => {
        act(() => logic.actions.setDraft('   \n  '))
        expectSendDisabled(true)
    })

    it('enables the send button when files are attached even with an empty draft', () => {
        act(() => logic.actions.setPendingFiles([new File(['x'], 'note.txt', { type: 'text/plain' })]))
        expect(logic.values.draft).toBe('')
        expectSendDisabled(false)
    })

    it('shows a Stop button instead of Send while the agent is busy', () => {
        act(() => logic.actions.setAgentBusy(true))
        expect(screen.getByLabelText('Stop')).toBeInTheDocument()
        expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument()
    })

    it('shows Send (not Stop) when the agent is idle', () => {
        expect(screen.getByLabelText('Send message')).toBeInTheDocument()
        expect(screen.queryByLabelText('Stop')).not.toBeInTheDocument()
    })

    it('cancels the run when the Stop button is clicked', () => {
        act(() => logic.actions.setAgentBusy(true))
        fireEvent.click(screen.getByLabelText('Stop'))
        expect(cancelRunSpy).toHaveBeenCalledTimes(1)
    })

    it('renders the attachment button in the addon bar', () => {
        expect(screen.getByLabelText('Attach files')).toBeInTheDocument()
    })

    it('does not render the attachments bar when there are no pending files', () => {
        expect(screen.queryByLabelText(/^Remove /)).not.toBeInTheDocument()
    })

    it('renders an attachments slot entry for each pending file', () => {
        act(() =>
            logic.actions.setPendingFiles([
                new File(['a'], 'first.txt', { type: 'text/plain' }),
                new File(['b'], 'second.txt', { type: 'text/plain' }),
            ])
        )
        expect(screen.getByLabelText('Remove first.txt')).toBeInTheDocument()
        expect(screen.getByLabelText('Remove second.txt')).toBeInTheDocument()
    })

    it('removes a pending file when its remove control is clicked', () => {
        act(() => logic.actions.setPendingFiles([new File(['a'], 'first.txt', { type: 'text/plain' })]))
        fireEvent.click(screen.getByLabelText('Remove first.txt'))
        expect(logic.values.pendingFiles).toHaveLength(0)
    })

    it('does not render the selector slots when no config options are present', () => {
        expect(screen.queryByText('Default')).not.toBeInTheDocument()
        expect(screen.queryByText('Sonnet')).not.toBeInTheDocument()
        expect(screen.queryByText(/^Effort:/)).not.toBeInTheDocument()
    })

    it('renders the mode, model, and effort selector slots from config options', () => {
        act(() => logic.actions.setConfigOptions([MODE_OPTION, MODEL_OPTION, THOUGHT_OPTION]))
        expect(screen.getByText('Default')).toBeInTheDocument()
        expect(screen.getByText('Sonnet')).toBeInTheDocument()
        expect(screen.getByText('Effort: Medium')).toBeInTheDocument()
    })

    it('changes a config option through the mode selector slot', () => {
        act(() => logic.actions.setConfigOptions([MODE_OPTION]))
        fireEvent.click(screen.getByText('Default'))
        fireEvent.click(screen.getByText('Plan'))
        expect(setConfigOptionSpy).toHaveBeenCalledWith('mode', 'plan')
    })
})
