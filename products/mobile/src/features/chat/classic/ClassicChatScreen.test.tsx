import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native'
import * as Clipboard from 'expo-clipboard'

import { useChatDraft } from '../useChatDraft'
import { ClassicChatScreen } from './ClassicChatScreen'
import { classicHistory, EMPTY_CLASSIC_STATE } from './classicMessages'
import { useClassicChat } from './useClassicChat'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))
jest.mock('../ChatAccessGate', () => ({ ChatAccessGate: ({ children }: { children: React.ReactNode }) => children }))
jest.mock('../ChatEmptyState', () => ({ ChatEmptyState: () => null }))
jest.mock('../ChatHeader', () => {
    const { Button, View } = require('react-native')
    return {
        CHAT_HEADER_HEIGHT: 52,
        ChatHeader: ({ onBack, onNewChat }: { onBack: () => void; onNewChat: () => void }) => (
            <View>
                <Button title="Back" onPress={onBack} />
                <Button title="New chat" onPress={onNewChat} />
            </View>
        ),
    }
})
jest.mock('../chatSheetEvents', () => ({
    useChatSheetEvents: () => ({ countSent: jest.fn(), countNewChat: jest.fn() }),
}))
jest.mock('../useChatDraft', () => ({ useChatDraft: jest.fn() }))
jest.mock('./useClassicChat', () => ({ useClassicChat: jest.fn() }))

function formChat(questions: Record<string, unknown>[]): ReturnType<typeof useClassicChat> {
    const state = classicHistory(
        [
            { id: 'question', type: 'human', content: 'Compare my events' },
            {
                id: 'form-message',
                type: 'ai',
                content: '',
                tool_calls: [{ id: 'form-call', name: 'create_form', args: { questions } }],
            },
        ],
        'Event comparison'
    )
    return {
        id: 'saved-chat',
        state,
        form: state.form,
        loading: false,
        working: false,
        stopping: false,
        historyError: null,
        error: null,
        send: jest.fn(),
        answer: jest.fn(),
        submitForm: jest.fn(),
        dismissForm: jest.fn(async () => true),
        stop: jest.fn(),
        reload: jest.fn(),
        reset: jest.fn(),
        dismissError: jest.fn(),
    }
}

function formScreen(): React.ReactElement {
    return (
        <ClassicChatScreen
            conversationId="saved-chat"
            source={{ entry: 'chats_list', origin: 'chat' }}
            autoFocus={false}
            onBack={jest.fn()}
            onNewChat={jest.fn()}
        />
    )
}

describe('classic chat draft recovery', () => {
    test.each([false, true])(
        'keeps custom multi-select typing separate from explicit selection %s across recovery',
        async (explicit) => {
            jest.mocked(useChatDraft).mockReturnValue({
                draft: { text: '', reportIds: [] },
                ready: true,
            } as unknown as ReturnType<typeof useChatDraft>)
            const chat = formChat([
                {
                    id: 'events',
                    title: 'Events',
                    question: 'Which events?',
                    type: 'multi_select',
                    options: [{ value: 'Signup' }],
                },
            ])
            chat.submitForm = jest.fn(async () => false)
            jest.mocked(useClassicChat).mockReturnValue(chat)
            const view = render(formScreen())
            if (explicit) fireEvent.press(screen.getByLabelText('Signup'))
            for (const letter of 'SignupX') {
                const input = screen.getByLabelText('Other answers')
                fireEvent.changeText(input, `${input.props.value}${letter}`)
            }
            if (explicit) expect(screen.getByLabelText('Signup')).toBeChecked()
            else expect(screen.getByLabelText('Signup')).not.toBeChecked()
            await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
            expect(chat.submitForm).toHaveBeenLastCalledWith({ events: explicit ? ['Signup', 'SignupX'] : ['SignupX'] })

            jest.mocked(useClassicChat).mockReturnValue({ ...chat, form: null, working: true })
            view.rerender(formScreen())
            jest.mocked(useClassicChat).mockReturnValue(chat)
            view.rerender(formScreen())
            expect(screen.getByDisplayValue('SignupX')).toBeTruthy()
            fireEvent.changeText(screen.getByLabelText('Other answers'), '')
            if (explicit) {
                expect(screen.getByLabelText('Signup')).toBeChecked()
                await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
                expect(chat.submitForm).toHaveBeenLastCalledWith({ events: ['Signup'] })
            } else {
                expect(screen.getByLabelText('Signup')).not.toBeChecked()
                expect(screen.getByLabelText('Submit answers')).toBeDisabled()
            }
        }
    )

    test('keeps a custom single-select answer while typing through a predefined option prefix', async () => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const chat = formChat([
            { id: 'region', title: 'Region', question: 'Which region?', options: [{ value: 'US' }] },
        ])
        chat.submitForm = jest.fn(async () => false)
        jest.mocked(useClassicChat).mockReturnValue(chat)
        render(formScreen())
        for (const letter of 'USA') {
            const input = screen.getByLabelText('Your answer')
            fireEvent.changeText(input, `${input.props.value}${letter}`)
        }
        expect(screen.getByDisplayValue('USA')).toBeTruthy()
        await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
        expect(chat.submitForm).toHaveBeenCalledWith({ region: 'USA' })
        fireEvent.press(screen.getByLabelText('US'))
        expect(screen.getByLabelText('Your answer')).toHaveDisplayValue('')
    })

    test.each([
        ['only the lowercase option', ['signup'], false],
        ['both case-distinct options', ['Signup', 'signup'], false],
        ['both options with custom answers enabled', ['Signup', 'signup'], true],
    ] as const)('preserves exact predefined multi-select values for %s', async (_name, selected, allowCustom) => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const chat = formChat([
            {
                id: 'events',
                title: 'Events',
                question: 'Which events?',
                type: 'multi_select',
                options: [{ value: 'Signup' }, { value: 'signup' }],
                allow_custom_answer: allowCustom,
            },
        ])
        chat.submitForm = jest.fn(async () => false)
        jest.mocked(useClassicChat).mockReturnValue(chat)
        render(formScreen())
        for (const option of selected) fireEvent.press(screen.getByLabelText(option))
        await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
        expect(chat.submitForm).toHaveBeenCalledWith({ events: [...selected] })
    })

    test('restores the same interrupt draft after an accepted resume temporarily removes the form', async () => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const chat = formChat([
            { id: 'region', title: 'Region', question: 'Which region?', options: [{ value: 'US' }] },
            {
                id: 'events',
                title: 'Events',
                question: 'Which events?',
                type: 'multi_select',
                options: [{ value: 'Signup' }],
            },
            { id: 'details', title: 'Details', question: 'Any details?' },
        ])
        let finish!: (accepted: boolean) => void
        chat.submitForm = jest.fn(
            () =>
                new Promise<boolean>((resolve) => {
                    finish = resolve
                })
        )
        jest.mocked(useClassicChat).mockReturnValue(chat)
        const view = render(formScreen())
        fireEvent.changeText(screen.getByPlaceholderText('Or type your answer'), 'Canada')
        fireEvent.press(screen.getByLabelText('Signup'))
        fireEvent.changeText(screen.getByLabelText('Other answers'), 'Activation\nInvite')
        fireEvent.press(screen.getByLabelText('Skip question: Details'))
        fireEvent.press(screen.getByLabelText('Submit answers'))

        jest.mocked(useClassicChat).mockReturnValue({ ...chat, form: null, working: true })
        view.rerender(formScreen())
        expect(screen.queryByTestId('classic-form')).toBeNull()
        await act(async () => finish(true))
        jest.mocked(useClassicChat).mockReturnValue(chat)
        view.rerender(formScreen())

        expect(screen.getByDisplayValue('Canada')).toBeTruthy()
        expect(screen.getByLabelText('Signup')).toBeChecked()
        expect(screen.getByDisplayValue('Activation\nInvite')).toBeTruthy()
        expect(screen.getByLabelText('Answer question: Details')).toBeTruthy()
        await act(async () => {
            fireEvent.press(screen.getByLabelText('Submit answers'))
            finish(false)
        })
        expect(chat.submitForm).toHaveBeenLastCalledWith({
            region: 'Canada',
            events: ['Signup', 'Activation', 'Invite'],
        })

        const pendingForm = chat.form
        if (!pendingForm) throw new Error('Expected a pending form')
        jest.mocked(useClassicChat).mockReturnValue({ ...chat, form: { ...pendingForm, id: 'next-interrupt' } })
        view.rerender(formScreen())
        expect(screen.queryByDisplayValue('Canada')).toBeNull()
        expect(screen.getByLabelText('Signup')).not.toBeChecked()
        expect(screen.getByLabelText('Skip question: Details')).toBeTruthy()

        fireEvent.changeText(screen.getByPlaceholderText('Or type your answer'), 'New draft')
        jest.mocked(useClassicChat).mockReturnValue({
            ...chat,
            form: null,
            working: true,
            state: {
                ...chat.state,
                messages: [
                    ...chat.state.messages,
                    {
                        id: 'form-result',
                        complete: true,
                        data: { type: 'tool', tool_call_id: 'next-interrupt', content: 'Answered' },
                    },
                ],
            },
        })
        view.rerender(formScreen())
        jest.mocked(useClassicChat).mockReturnValue({ ...chat, form: { ...pendingForm, id: 'next-interrupt' } })
        view.rerender(formScreen())
        expect(screen.queryByDisplayValue('New draft')).toBeNull()
    })

    test('answers native form selections and composite fields, retaining values after a failed submission', async () => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const chat = formChat([
            {
                id: 'range',
                title: 'Range',
                question: 'Which range?',
                options: [{ value: 'Last week' }],
                allow_custom_answer: false,
            },
            {
                id: 'events',
                title: 'Events',
                question: 'Which events?',
                type: 'multi_select',
                options: [{ value: 'Signup' }, { value: 'Purchase' }],
            },
            {
                id: 'details',
                title: 'Details',
                question: 'Which settings?',
                type: 'multi_field',
                fields: [
                    { id: 'segment', type: 'text', label: 'Segment' },
                    { id: 'limit', type: 'number', label: 'Limit', min: 5, max: 15, step: 5 },
                    { id: 'threshold', type: 'slider', label: 'Threshold', min: 10, max: 20, step: 5 },
                    { id: 'returning', type: 'toggle', label: 'Returning users' },
                    { id: 'group', type: 'dropdown', label: 'Group', options: [{ value: 'Country' }] },
                ],
            },
        ])
        let finish!: (accepted: boolean) => void
        chat.submitForm = jest.fn(
            () =>
                new Promise<boolean>((resolve) => {
                    finish = resolve
                })
        )
        jest.mocked(useClassicChat).mockReturnValue(chat)
        render(formScreen())
        expect(screen.getByTestId('classic-form')).toBeTruthy()
        expect(screen.queryByTestId('chat-input')).toBeNull()
        expect(screen.getByLabelText('Submit answers')).toBeDisabled()
        fireEvent.press(screen.getByLabelText('Last week'))
        fireEvent.press(screen.getByLabelText('Signup'))
        fireEvent.press(screen.getByLabelText('Purchase'))
        fireEvent.changeText(screen.getByLabelText('Other answers'), 'Activation\nInvite\nsignup\nactivation')
        fireEvent.changeText(screen.getByLabelText('Segment'), 'New accounts')
        fireEvent.changeText(screen.getByLabelText('Limit'), '7')
        fireEvent.press(screen.getByLabelText('Country'))
        expect(screen.getByLabelText('Submit answers')).toBeDisabled()
        fireEvent.changeText(screen.getByLabelText('Limit'), '10')
        expect(screen.getByLabelText('Submit answers')).toBeEnabled()
        fireEvent.press(screen.getByLabelText('Submit answers'))
        fireEvent.press(screen.getByLabelText('Submit answers'))
        expect(chat.submitForm).toHaveBeenCalledTimes(1)
        expect(chat.submitForm).toHaveBeenCalledWith({
            range: 'Last week',
            events: ['Signup', 'Purchase', 'Activation', 'Invite'],
            segment: 'New accounts',
            limit: '10',
            threshold: '10',
            returning: 'false',
            group: 'Country',
        })
        expect(screen.getByLabelText('Dismiss form')).toBeDisabled()
        await act(async () => finish(false))
        expect(screen.getByDisplayValue('New accounts')).toBeTruthy()
        expect(screen.getByLabelText('Signup')).toBeChecked()
        expect(screen.getByLabelText('Submit answers')).toBeEnabled()
        expect(chat.send).not.toHaveBeenCalled()
    })

    test('skips individual questions without sending their fields and offers dismissal for unsupported forms', async () => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const chat = formChat([
            { id: 'range', title: 'Range', question: 'Which range?', options: [{ value: 'Last week' }] },
            {
                id: 'details',
                title: 'Details',
                question: 'Which settings?',
                type: 'multi_field',
                fields: [
                    { id: 'enabled', label: 'Enabled', type: 'toggle' },
                    { id: 'segment', type: 'text', label: 'Segment' },
                ],
            },
        ])
        chat.submitForm = jest.fn(async () => false)
        jest.mocked(useClassicChat).mockReturnValue(chat)
        const view = render(formScreen())
        fireEvent.press(screen.getByLabelText('Last week'))
        fireEvent.press(screen.getByLabelText('Skip question: Details'))
        await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
        expect(chat.submitForm).toHaveBeenCalledWith({ range: 'Last week' })

        const unsupported = formChat([
            { id: 'future', title: 'Future', question: 'A future question', type: 'future_type' },
        ])
        jest.mocked(useClassicChat).mockReturnValue(unsupported)
        view.rerender(formScreen())
        expect(screen.getByText(/This form needs the web app/)).toBeTruthy()
        expect(screen.queryByLabelText('Submit answers')).toBeNull()
        await act(async () => fireEvent.press(screen.getByLabelText('Dismiss form')))
        expect(unsupported.dismissForm).toHaveBeenCalledTimes(1)
    })

    test('adds streamed composite defaults without replacing an answer already entered', async () => {
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        const first = formChat([{ id: 'name', title: 'Name', question: 'Which segment?' }])
        jest.mocked(useClassicChat).mockReturnValue(first)
        const view = render(formScreen())
        fireEvent.changeText(screen.getByLabelText('Your answer'), 'New accounts')
        const complete = formChat([
            { id: 'name', title: 'Name', question: 'Which segment?' },
            {
                id: 'settings',
                title: 'Settings',
                question: 'Which settings?',
                type: 'multi_field',
                fields: [
                    { id: 'enabled', type: 'toggle', label: 'Enabled' },
                    { id: 'threshold', type: 'slider', label: 'Threshold', min: 5 },
                ],
            },
        ])
        complete.submitForm = jest.fn(async () => false)
        jest.mocked(useClassicChat).mockReturnValue(complete)
        view.rerender(formScreen())
        expect(screen.getByDisplayValue('New accounts')).toBeTruthy()
        expect(screen.getByDisplayValue('5')).toBeTruthy()
        await act(async () => fireEvent.press(screen.getByLabelText('Submit answers')))
        expect(complete.submitForm).toHaveBeenCalledWith({ name: 'New accounts', enabled: 'false', threshold: '5' })
    })

    test('keeps tool commentary collapsed while the final answer stays readable and copyable', async () => {
        const copy = jest.spyOn(Clipboard, 'setStringAsync').mockResolvedValue(true)
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: '', reportIds: [] },
            ready: true,
        } as unknown as ReturnType<typeof useChatDraft>)
        jest.mocked(useClassicChat).mockReturnValue({
            id: 'saved-chat',
            loading: false,
            working: false,
            stopping: false,
            historyError: null,
            error: null,
            state: classicHistory(
                [
                    { id: 'question', type: 'human', content: 'Compare signup events.' },
                    {
                        id: 'inspection',
                        type: 'ai',
                        content: 'Inspecting the selected events.',
                        meta: { thinking: [{ type: 'thinking', thinking: 'Use the same date range.' }] },
                        tool_calls: [{ id: 'query', name: 'query_insight', args: {} }],
                    },
                    { id: 'query-result', type: 'tool', tool_call_id: 'query', content: 'Done.' },
                    { id: 'answer', type: 'ai', content: 'Signups increased.' },
                ],
                'Signup comparison'
            ),
        } as unknown as ReturnType<typeof useClassicChat>)
        render(
            <ClassicChatScreen
                conversationId="saved-chat"
                source={{ entry: 'chats_list', origin: 'chat' }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        expect(screen.getByText('Signups increased.')).toBeTruthy()
        expect(screen.queryByText('Inspecting the selected events.')).toBeNull()
        expect(screen.queryByText('Use the same date range.')).toBeNull()
        fireEvent.press(screen.getByLabelText('1 tool call'))
        expect(screen.getByText('Inspecting the selected events.')).toBeTruthy()
        expect(screen.getByText('Use the same date range.')).toBeTruthy()
        fireEvent.press(within(screen.getByTestId('session-assistant')).getByLabelText('Copy message text'))
        await waitFor(() => expect(copy).toHaveBeenCalledWith('Signups increased.'))
        copy.mockRestore()
    })
    test.each(['empty', 'partial', 'reloading'] as const)(
        'keeps %s history recoverable without hiding received messages',
        (kind) => {
            const reload = jest.fn(async () => undefined)
            jest.mocked(useChatDraft).mockReturnValue({
                draft: { text: '', reportIds: [] },
                ready: true,
            } as unknown as ReturnType<typeof useChatDraft>)
            jest.mocked(useClassicChat).mockReturnValue({
                id: 'saved-chat',
                loading: kind === 'reloading',
                working: false,
                stopping: false,
                historyError: kind === 'reloading' ? null : 'The reply was interrupted.',
                error: null,
                state: classicHistory(
                    kind === 'empty' ? [] : [{ id: 'reply-1', type: 'ai', content: 'Received reply' }],
                    'A chat'
                ),
                form: null,
                send: jest.fn(),
                answer: jest.fn(),
                submitForm: jest.fn(),
                dismissForm: jest.fn(),
                stop: jest.fn(),
                reload,
                reset: jest.fn(),
                dismissError: jest.fn(),
            })
            render(
                <ClassicChatScreen
                    conversationId="saved-chat"
                    source={{ entry: 'chats_list', origin: 'chat' }}
                    autoFocus={false}
                    onBack={jest.fn()}
                    onNewChat={jest.fn()}
                />
            )
            if (kind === 'empty') {
                expect(screen.getByText("Couldn't load this session")).toBeTruthy()
                fireEvent.press(screen.getByText('Try again'))
            } else {
                expect(screen.getByText('Received reply')).toBeTruthy()
                expect(screen.queryByText("Couldn't load this session")).toBeNull()
                if (kind === 'reloading') {
                    expect(screen.queryByLabelText('Reconnect')).toBeNull()
                    expect(screen.queryByText('Reconnecting…')).toBeNull()
                } else {
                    fireEvent.press(screen.getByLabelText('Reconnect'))
                }
            }
            expect(reload).toHaveBeenCalledTimes(kind === 'reloading' ? 0 : 1)
        }
    )
    test('keeps the unsaved text visible and guards retry until storage settles', async () => {
        let finish!: () => void
        const retrySave = jest.fn(
            () =>
                new Promise<void>((resolve) => {
                    finish = resolve
                })
        )
        const draft = {
            draft: { text: 'Saved question', reportIds: [] },
            ready: true,
            draftError: 'Draft not saved. Try saving again.',
            retrySave,
        } as unknown as ReturnType<typeof useChatDraft>
        jest.mocked(useChatDraft).mockReturnValue(draft)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            historyError: null,
            working: false,
            error: 'Reply failed. Try again.',
            state: { messages: [], title: null, approval: null, progress: null, error: null },
        } as unknown as ReturnType<typeof useClassicChat>)
        const element = (
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        const view = render(element)
        expect(screen.getByDisplayValue('Saved question')).toBeTruthy()
        expect(screen.getByText(draft.draftError as string)).toBeTruthy()
        expect(screen.getByText('Reply failed. Try again.')).toBeTruthy()
        fireEvent.press(screen.getByLabelText('Retry saving draft'))
        fireEvent.press(screen.getByLabelText('Retry saving draft'))
        expect(retrySave).toHaveBeenCalledTimes(1)
        await act(async () => {
            finish()
        })
        draft.draftError = undefined
        view.rerender(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        expect(screen.queryByLabelText('Retry saving draft')).toBeNull()
        expect(screen.getByDisplayValue('Saved question')).toBeTruthy()
    })
    test.each(['Back', 'New chat', 'unmount'])('restores a prepared draft after %s', async (transition) => {
        let finish!: (settle: (sent: boolean) => Promise<void>) => void
        const settle = jest.fn(async () => undefined)
        const send = jest.fn()
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: 'Unsent question', reportIds: [] },
            ready: true,
            beginSend: () =>
                new Promise((resolve) => {
                    finish = resolve
                }),
        } as unknown as ReturnType<typeof useChatDraft>)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            working: false,
            state: { messages: [], approval: null },
            send,
            reset: jest.fn(),
        } as unknown as ReturnType<typeof useClassicChat>)
        const view = render(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        fireEvent.press(screen.getByTestId('chat-send'))
        if (transition === 'unmount') view.unmount()
        else fireEvent.press(screen.getByText(transition))
        await act(async () => {
            finish(settle)
        })
        expect(send).not.toHaveBeenCalled()
        expect(settle).toHaveBeenCalledWith(false)
    })
    test('settles an accepted draft while the reply is still streaming', async () => {
        const settle = jest.fn(async () => undefined)
        let finish!: (accepted: boolean) => void
        jest.mocked(useChatDraft).mockReturnValue({
            draft: { text: 'A question', reportIds: [] },
            ready: true,
            beginSend: async () => settle,
        } as unknown as ReturnType<typeof useChatDraft>)
        jest.mocked(useClassicChat).mockReturnValue({
            id: null,
            loading: false,
            working: false,
            historyError: null,
            stopping: false,
            error: null,
            state: EMPTY_CLASSIC_STATE,
            answer: jest.fn(),
            form: null,
            submitForm: jest.fn(),
            dismissForm: jest.fn(),
            stop: jest.fn(),
            reload: jest.fn(),
            reset: jest.fn(),
            dismissError: jest.fn(),
            send: async (_text, onAccepted) => {
                await onAccepted?.()
                return new Promise((resolve) => {
                    finish = resolve
                })
            },
        })
        render(
            <ClassicChatScreen
                source={{ entry: 'compose', origin: null }}
                autoFocus={false}
                onBack={jest.fn()}
                onNewChat={jest.fn()}
            />
        )
        fireEvent.press(screen.getByTestId('chat-send'))
        await waitFor(() => expect(settle).toHaveBeenCalledWith(true))
        await act(async () => {
            finish(true)
        })
        expect(settle).toHaveBeenCalledTimes(1)
    })
})
