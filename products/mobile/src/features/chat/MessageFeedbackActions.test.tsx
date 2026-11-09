import { act, fireEvent, render, screen } from '@testing-library/react-native'

import { setAnalyticsClient } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'

import type { ChatFeedbackTarget } from './chatFeedback'
import { useChatFeedbackStore } from './chatFeedbackStore'
import { MessageFeedbackActions } from './MessageFeedbackActions'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => ({
    useReanimatedKeyboardAnimation: () => ({ height: { value: 0 } }),
}))
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))

const TARGET: ChatFeedbackTarget = {
    sessionId: 'task-1',
    runtime: 'sandbox',
    traceId: 'trace-1',
    runId: 'original-run',
    turnIndex: 2,
}

describe('message feedback actions', () => {
    const capture = jest.fn()

    beforeEach(async () => {
        await act(async () => {
            await useChatFeedbackStore.persist.rehydrate()
            useChatFeedbackStore.setState({ responses: {}, hydrated: true })
        })
        capture.mockClear()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
    })

    afterEach(() => setAnalyticsClient(null))

    test('records a good rating once and restores its selection when the answer remounts', async () => {
        const view = render(<MessageFeedbackActions target={TARGET} />, { wrapper: OverlayHost })
        fireEvent.press(screen.getByLabelText('Good answer'))
        fireEvent.press(screen.getByLabelText('Good answer'))
        expect(capture).toHaveBeenCalledTimes(1)
        expect(capture).toHaveBeenCalledWith(
            '$ai_metric',
            expect.objectContaining({
                $ai_metric_name: 'quality',
                $ai_metric_value: 'good',
                $ai_session_id: 'task-1',
                $ai_trace_id: 'trace-1',
                run_id: 'original-run',
                turn_index: 2,
                agent_runtime: 'sandbox',
            })
        )
        expect(screen.getByLabelText('Good answer')).toBeSelected()
        expect(screen.queryByLabelText('Bad answer')).toBeNull()
        view.unmount()
        await act(async () => useChatFeedbackStore.persist.rehydrate())
        render(<MessageFeedbackActions target={TARGET} />, { wrapper: OverlayHost })
        expect(screen.getByLabelText('Good answer')).toBeSelected()
    })

    test('keeps a bad rating when the comment is skipped, then sends the optional comment only once', () => {
        render(<MessageFeedbackActions target={TARGET} />, { wrapper: OverlayHost })
        fireEvent.press(screen.getByLabelText('Bad answer'))
        expect(screen.getByTestId('chat-feedback-sheet')).toBeTruthy()
        expect(screen.getByTestId('chat-feedback-submit')).toBeDisabled()
        fireEvent.press(screen.getByText('Skip'))
        expect(screen.queryByTestId('chat-feedback-sheet')).toBeNull()
        expect(screen.getByLabelText('Bad answer')).toBeSelected()

        fireEvent.press(screen.getByLabelText('Bad answer'))
        fireEvent.changeText(screen.getByLabelText('Feedback about this answer'), '  The explanation needs a source.  ')
        fireEvent.press(screen.getByTestId('chat-feedback-submit'))
        expect(screen.queryByTestId('chat-feedback-sheet')).toBeNull()
        fireEvent.press(screen.getByLabelText('Bad answer'))
        expect(capture.mock.calls.filter(([event]) => event === '$ai_metric')).toHaveLength(1)
        expect(capture.mock.calls.filter(([event]) => event === '$ai_feedback')).toHaveLength(1)
        expect(capture).toHaveBeenCalledWith(
            '$ai_feedback',
            expect.objectContaining({
                $ai_feedback_text: 'The explanation needs a source.',
                $ai_trace_id: 'trace-1',
                run_id: 'original-run',
            })
        )
    })
})
