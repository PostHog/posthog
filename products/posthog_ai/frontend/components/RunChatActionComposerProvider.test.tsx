import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { runInteractionLogic } from '../logics/runInteractionLogic'
import { useChatActionComposer } from './ChatActionComposerContext'
import { RunChatActionComposerProvider } from './RunChatActionComposerProvider'

// The composer logic is reduced to the state and actions this provider reads and dispatches, so the
// test controls the draft, the staged files, and the in-flight states directly.
jest.mock('../logics/runInteractionLogic', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    return {
        runInteractionLogic: kea([
            path(['test', 'runInteractionLogicStub']),
            props({}),
            key((p: { runId: string }) => p.runId),
            actions({
                setComposerFormValues: (values: { draft: string }) => ({ values }),
                setComposerFocused: (focused: boolean) => ({ focused }),
                submitComposerForm: true,
                setStubCancelling: (state: string | null) => ({ state }),
                setStubAttachments: (attachments: unknown[]) => ({ attachments }),
                setStubSubmitting: (submitting: boolean) => ({ submitting }),
                setStubPendingRequest: (pending: boolean) => ({ pending }),
            }),
            reducers({
                composerForm: [
                    { draft: '' },
                    {
                        setComposerFormValues: (_: unknown, { values }: { values: { draft: string } }) => values,
                    },
                ],
                cancellationState: [
                    null as string | null,
                    { setStubCancelling: (_: unknown, { state }: { state: string | null }) => state },
                ],
                stagedAttachments: [
                    [] as unknown[],
                    { setStubAttachments: (_: unknown, { attachments }: { attachments: unknown[] }) => attachments },
                ],
                composerActive: [
                    true,
                    { setStubPendingRequest: (_: boolean, { pending }: { pending: boolean }) => !pending },
                ],
                isSubmitting: [
                    false,
                    { setStubSubmitting: (_: unknown, { submitting }: { submitting: boolean }) => submitting },
                ],
            }),
        ]),
    }
})

/** Stands in for the composer's debounced local draft, which `flushDraft` pushes into the logic. */
let pendingDraft: string | null = null
const LOGIC_PROPS = {
    taskId: 'task-1',
    runId: 'run-1',
    flushDraft: () => {
        if (pendingDraft !== null) {
            runInteractionLogic.findMounted({ taskId: 'task-1', runId: 'run-1' })?.actions.setComposerFormValues({
                draft: pendingDraft,
            })
            pendingDraft = null
        }
    },
}

interface StubActions {
    setStubCancelling: (state: string | null) => void
    setStubAttachments: (attachments: unknown[]) => void
    setStubSubmitting: (submitting: boolean) => void
    setStubPendingRequest: (pending: boolean) => void
}

/** The stub's test-only actions, absent from the real logic's type. */
const stubActions = (logic: ReturnType<typeof runInteractionLogic>): StubActions =>
    logic.actions as unknown as StubActions

/** Exposes the provided composer as buttons, standing in for the suggested-action widget. */
function Probe(): JSX.Element {
    const composer = useChatActionComposer()
    if (!composer) {
        return <span>no composer</span>
    }
    return (
        <>
            <button onClick={() => composer.insert('Send a test email of this workflow to ')}>insert</button>
            <button onClick={() => composer.send('Enable workflow wf_1.')}>send</button>
            <span data-attr="reason">{composer.sendDisabledReason ?? 'none'}</span>
            <span>insert: {composer.insertDisabledReason ?? 'live'}</span>
        </>
    )
}

describe('RunChatActionComposerProvider', () => {
    let logic: ReturnType<typeof runInteractionLogic>
    let focusComposer: jest.Mock

    const renderProvider = (readOnly = false): void => {
        render(
            <RunChatActionComposerProvider logicProps={LOGIC_PROPS} focusComposer={focusComposer} readOnly={readOnly}>
                <Probe />
            </RunChatActionComposerProvider>
        )
    }

    beforeEach(() => {
        pendingDraft = null
        focusComposer = jest.fn()
        initKeaTests()
        logic = runInteractionLogic(LOGIC_PROPS)
        logic.mount()
    })
    afterEach(cleanup)

    it('insert fills an empty composer and focuses it without sending', async () => {
        renderProvider()
        fireEvent.click(screen.getByText('insert'))
        await expectLogic(logic)
            .toDispatchActions([
                logic.actionCreators.setComposerFormValues({ draft: 'Send a test email of this workflow to ' }),
            ])
            .toNotHaveDispatchedActions(['submitComposerForm'])
        expect(focusComposer).toHaveBeenCalledTimes(1)
    })

    it('blocks insert while a pending request hides the composer', async () => {
        renderProvider()
        expect(screen.getByText('insert: live')).toBeInTheDocument()
        stubActions(logic).setStubPendingRequest(true)
        expect(await screen.findByText('insert: Answer the request below first')).toBeInTheDocument()
    })

    // Stopping hides the request card and shows the composer again, so insert must stay usable.
    it('keeps insert live while a stopping run has a pending request', async () => {
        renderProvider()
        stubActions(logic).setStubPendingRequest(true)
        expect(await screen.findByText('insert: Answer the request below first')).toBeInTheDocument()
        stubActions(logic).setStubCancelling('cancelling')
        expect(await screen.findByText('insert: live')).toBeInTheDocument()
    })

    it('gives a read-only view no composer', () => {
        renderProvider(true)
        expect(screen.getByText('no composer')).toBeInTheDocument()
    })

    // A click must not destroy what the user was typing, including keystrokes the composer has not
    // pushed into the logic yet.
    it.each([
        ['already in the logic', () => logic.actions.setComposerFormValues({ draft: 'Also rename it ' })],
        ['still pending in the composer', () => (pendingDraft = 'Also rename it ')],
    ])('insert keeps a draft %s above the message', async (_case, arrange) => {
        renderProvider()
        arrange()
        fireEvent.click(screen.getByText('insert'))
        await expectLogic(logic).toMatchValues({
            composerForm: { draft: 'Also rename it\nSend a test email of this workflow to ' },
        })
    })

    it('send replaces the draft with the message and submits', async () => {
        renderProvider()
        fireEvent.click(screen.getByText('send'))
        await expectLogic(logic).toDispatchActions([
            logic.actionCreators.setComposerFormValues({ draft: 'Enable workflow wf_1.' }),
            'submitComposerForm',
        ])
    })

    it('send leaves keystrokes the composer has not pushed yet alone and submits nothing', async () => {
        renderProvider()
        pendingDraft = 'wip'
        fireEvent.click(screen.getByText('send'))
        await expectLogic(logic)
            .toMatchValues({ composerForm: { draft: 'wip' } })
            .toNotHaveDispatchedActions(['submitComposerForm'])
    })

    it.each([
        [
            'a draft in progress',
            () => logic.actions.setComposerFormValues({ draft: 'wip' }),
            'Send or clear your draft first',
        ],
        [
            'a run that is stopping',
            () => stubActions(logic).setStubCancelling('cancelling'),
            'Wait for the run to stop',
        ],
        [
            'files staged without text',
            () => stubActions(logic).setStubAttachments([{ id: 'file-1' }]),
            'Send or clear your draft first',
        ],
        ['a message being sent', () => stubActions(logic).setStubSubmitting(true), 'Wait for your message to send'],
    ])('reports why send is blocked during %s', async (_case, arrange, reason) => {
        renderProvider()
        expect(screen.getByText('none')).toBeInTheDocument()
        arrange()
        expect(await screen.findByText(reason)).toBeInTheDocument()
    })
})
