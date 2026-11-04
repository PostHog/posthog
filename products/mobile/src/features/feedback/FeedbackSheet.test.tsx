import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import { useKeyboardState } from 'react-native-keyboard-controller'

import { setAnalyticsClient } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'
import { SceneDimensionsContext } from '@/ui/sceneDimensions'
import { FeedbackSheet } from './FeedbackSheet'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))

describe('FeedbackSheet', () => {
    beforeEach(() => jest.mocked(useKeyboardState).mockReturnValue(0))
    afterEach(() => setAnalyticsClient(null))

    test('allows dismissal during delivery and sends once across reopening', async () => {
        const capture = jest.fn()
        let deliver!: () => void
        const delivery = new Promise<void>((resolve) => {
            deliver = resolve
        })
        const flush = jest.fn().mockResolvedValueOnce(undefined).mockReturnValueOnce(delivery)
        setAnalyticsClient({ capture, flush, identify: jest.fn(), reset: jest.fn() })
        const onClose = jest.fn()
        const onSent = jest.fn()
        const props = { email: 'person@example.com', onClose, onSent }
        const { rerender } = render(<FeedbackSheet visible {...props} />, { wrapper: OverlayHost })

        fireEvent.changeText(screen.getByTestId('feedback-message'), '   ')
        expect(screen.getByTestId('feedback-send')).toBeDisabled()

        fireEvent.changeText(screen.getByTestId('feedback-message'), '  The inbox needs a search.  ')
        fireEvent.press(screen.getByTestId('feedback-send'))
        fireEvent.press(screen.getByTestId('feedback-send'))
        fireEvent.press(screen.getByLabelText('Close', { includeHiddenElements: true }))
        expect(screen.getByTestId('feedback-send')).toBeDisabled()
        expect(screen.getByLabelText('Sending feedback')).toBeOnTheScreen()
        expect(onSent).not.toHaveBeenCalled()
        expect(onClose).toHaveBeenCalledTimes(1)
        rerender(<FeedbackSheet visible={false} {...props} />)
        rerender(<FeedbackSheet visible {...props} />)
        expect(screen.getByTestId('feedback-message')).toHaveProp('value', '  The inbox needs a search.  ')
        expect(screen.getByTestId('feedback-send')).toBeDisabled()
        fireEvent.press(screen.getByTestId('feedback-send'))

        await act(async () => deliver())
        fireEvent.press(screen.getByLabelText('Close', { includeHiddenElements: true }))

        const events = capture.mock.calls.map(([event]) => event)
        expect(events).toEqual(['survey shown', 'survey sent', 'survey dismissed', 'survey shown'])
        const sent = capture.mock.calls[1][1]
        expect(sent).toMatchObject({
            $survey_response: 'The inbox needs a search.',
            $survey_completed: true,
            email: 'person@example.com',
        })
        // Survey results read the question-keyed response, and the Slack message reads `$survey_response`.
        const questionKeys = Object.keys(sent).filter((key) => key.startsWith('$survey_response_'))
        expect(questionKeys.map((key) => sent[key])).toEqual(['The inbox needs a search.'])
        expect(flush).toHaveBeenCalledTimes(4)
        expect(onSent).toHaveBeenCalledTimes(1)
        expect(onClose).toHaveBeenCalledTimes(2)
    })

    test.each(['HTTP 429', 'HTTP 503', 'Network request failed'])(
        'keeps the draft after %s, including across reopening, and allows retry',
        async (failure) => {
            const capture = jest.fn()
            const flush = jest.fn().mockResolvedValue(undefined).mockRejectedValueOnce(new Error(failure))
            setAnalyticsClient({ capture, flush, identify: jest.fn(), reset: jest.fn() })
            const props = { email: 'person@example.com', onClose: jest.fn(), onSent: jest.fn() }
            const { rerender } = render(<FeedbackSheet visible {...props} />, { wrapper: OverlayHost })
            flush.mockRejectedValueOnce(new Error(failure))
            fireEvent.changeText(screen.getByTestId('feedback-message'), 'Keep this draft.')
            fireEvent.press(screen.getByTestId('feedback-send'))
            await waitFor(() => expect(screen.getByTestId('feedback-error')).toBeOnTheScreen())
            expect(props.onSent).not.toHaveBeenCalled()
            expect(screen.getByTestId('feedback-message')).toHaveProp('value', 'Keep this draft.')
            expect(screen.getByTestId('feedback-send')).not.toBeDisabled()
            fireEvent.press(screen.getByLabelText('Close', { includeHiddenElements: true }))
            rerender(<FeedbackSheet visible={false} {...props} />)
            rerender(<FeedbackSheet visible {...props} />)
            expect(screen.getByTestId('feedback-message')).toHaveProp('value', 'Keep this draft.')
            fireEvent.press(screen.getByTestId('feedback-send'))
            await waitFor(() => expect(props.onSent).toHaveBeenCalledTimes(1))
            const submissions = capture.mock.calls.filter(([event]) => event === 'survey sent')
            expect(submissions).toHaveLength(2)
            expect(submissions[1][1]).toEqual(submissions[0][1])
            expect(screen.getByTestId('feedback-message')).toHaveProp('value', '')
        }
    )

    test.each([
        [320, 0],
        [667, 300],
        [667, 0],
    ])('discloses email sharing at scene height %s with keyboard height %s', (height, keyboardHeight) => {
        jest.mocked(useKeyboardState).mockReturnValue(keyboardHeight)
        render(
            <SceneDimensionsContext.Provider value={{ width: 375, height }}>
                <FeedbackSheet visible email="person@example.com" onClose={jest.fn()} onSent={jest.fn()} />
            </SceneDimensionsContext.Provider>,
            { wrapper: OverlayHost }
        )
        expect(screen.getByTestId('feedback-description')).toHaveTextContent(/PostHog team/)
        expect(screen.getByTestId('feedback-description')).toHaveTextContent(/email/)
        expect(screen.getByTestId('feedback-description')).toHaveTextContent(/person@example\.com/)
        if (height - keyboardHeight < 480) {
            expect(screen.getByTestId('feedback-description')).toHaveTextContent(/Send a message to the PostHog team/)
        }
    })
})
