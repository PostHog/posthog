import { fireEvent, render, screen } from '@testing-library/react-native'

import { setAnalyticsClient } from '@/lib/analytics'
import { OverlayHost } from '@/ui/OverlayPortal'
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

afterEach(() => setAnalyticsClient(null))

test('sends the trimmed message once with the email, and a close after sending is not a dismissal', () => {
    const capture = jest.fn()
    const flush = jest.fn(async () => undefined)
    setAnalyticsClient({ capture, flush, identify: jest.fn(), reset: jest.fn() })
    const onClose = jest.fn()
    const onSent = jest.fn()
    render(<FeedbackSheet visible email="person@example.com" onClose={onClose} onSent={onSent} />, {
        wrapper: OverlayHost,
    })

    fireEvent.changeText(screen.getByTestId('feedback-message'), '   ')
    expect(screen.getByTestId('feedback-send')).toBeDisabled()

    fireEvent.changeText(screen.getByTestId('feedback-message'), '  The inbox needs a search.  ')
    fireEvent.press(screen.getByTestId('feedback-send'))
    fireEvent.press(screen.getByTestId('feedback-send'))
    fireEvent.press(screen.getByLabelText('Close', { includeHiddenElements: true }))

    const events = capture.mock.calls.map(([event]) => event)
    expect(events).toEqual(['survey shown', 'survey sent'])
    const sent = capture.mock.calls[1][1]
    expect(sent).toMatchObject({
        $survey_response: 'The inbox needs a search.',
        $survey_completed: true,
        email: 'person@example.com',
    })
    // Survey results read the question-keyed response, and the Slack message reads `$survey_response`.
    const questionKeys = Object.keys(sent).filter((key) => key.startsWith('$survey_response_'))
    expect(questionKeys.map((key) => sent[key])).toEqual(['The inbox needs a search.'])
    expect(flush).toHaveBeenCalledTimes(2)
    expect(onSent).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
})
