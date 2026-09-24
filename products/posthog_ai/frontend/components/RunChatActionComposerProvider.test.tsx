import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { runInteractionLogic } from '../logics/runInteractionLogic'
import { useChatActionComposer } from './ChatActionComposerContext'
import { RunChatActionComposerProvider } from './RunChatActionComposerProvider'

// The composer logic is reduced to the state and actions this provider reads and dispatches, so the
// test controls the draft and the cancellation state directly.
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
            }),
        ]),
    }
})

const LOGIC_PROPS = { taskId: 'task-1', runId: 'run-1' }

/** The stub's test-only action, absent from the real logic's type. */
const stubActions = (
    logic: ReturnType<typeof runInteractionLogic>
): { setStubCancelling: (state: string | null) => void } =>
    logic.actions as unknown as { setStubCancelling: (state: string | null) => void }

/** Exposes the provided composer as buttons, standing in for the suggested-action widget. */
function Probe(): JSX.Element {
    const composer = useChatActionComposer()!
    return (
        <>
            <button onClick={() => composer.insert('Send a real test of this workflow to ')}>insert</button>
            <button onClick={() => composer.send('Enable workflow wf_1.')}>send</button>
            <span data-attr="reason">{composer.sendDisabledReason ?? 'none'}</span>
        </>
    )
}

describe('RunChatActionComposerProvider', () => {
    let logic: ReturnType<typeof runInteractionLogic>

    beforeEach(() => {
        initKeaTests()
        logic = runInteractionLogic(LOGIC_PROPS)
        logic.mount()
        render(
            <RunChatActionComposerProvider logicProps={LOGIC_PROPS}>
                <Probe />
            </RunChatActionComposerProvider>
        )
    })
    afterEach(cleanup)

    it('insert fills an empty composer and focuses it without sending', async () => {
        fireEvent.click(screen.getByText('insert'))
        await expectLogic(logic)
            .toDispatchActions([
                logic.actionCreators.setComposerFormValues({ draft: 'Send a real test of this workflow to ' }),
                logic.actionCreators.setComposerFocused(true),
            ])
            .toNotHaveDispatchedActions(['submitComposerForm'])
    })

    // A click must not destroy what the user was typing.
    it('insert keeps a draft in progress above the message', async () => {
        logic.actions.setComposerFormValues({ draft: 'Also rename it ' })
        fireEvent.click(screen.getByText('insert'))
        await expectLogic(logic).toMatchValues({
            composerForm: { draft: 'Also rename it\nSend a real test of this workflow to ' },
        })
    })

    it('send replaces the draft with the message and submits', async () => {
        fireEvent.click(screen.getByText('send'))
        await expectLogic(logic).toDispatchActions([
            logic.actionCreators.setComposerFormValues({ draft: 'Enable workflow wf_1.' }),
            'submitComposerForm',
        ])
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
    ])('reports why send is blocked during %s', async (_case, arrange, reason) => {
        expect(screen.getByText('none')).toBeInTheDocument()
        arrange()
        expect(await screen.findByText(reason)).toBeInTheDocument()
    })
})
