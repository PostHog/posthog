import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { TurnFeedbackActions } from './TurnFeedbackActions'

type CloseAction = 'submit' | 'shortcut' | 'cancel'

describe('TurnFeedbackActions', () => {
    let captureSpy: jest.SpyInstance
    let toastSpy: jest.SpyInstance

    beforeEach(() => {
        // Ratings persist to localStorage, so one case's rating would leak into the next.
        localStorage.clear()
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        toastSpy = jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast-id')
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    test.each<{ name: string; typed: string; close: CloseAction; expectedEvents: [string, object][]; toast: boolean }>([
        {
            name: 'submitting without text',
            typed: '',
            close: 'submit',
            expectedEvents: [
                ['$ai_metric', { $ai_metric_value: 'bad' }],
                ['posthog ai feedback dialog closed', { outcome: 'submitted', has_text: false }],
            ],
            toast: true,
        },
        {
            name: 'submitting text',
            typed: '  The numbers were wrong  ',
            close: 'submit',
            expectedEvents: [
                ['$ai_metric', { $ai_metric_value: 'bad' }],
                ['$ai_feedback', { $ai_feedback_text: 'The numbers were wrong' }],
                ['posthog ai feedback dialog closed', { outcome: 'submitted', has_text: true }],
            ],
            toast: true,
        },
        {
            name: 'submitting with the keyboard shortcut',
            typed: 'Too long',
            close: 'shortcut',
            expectedEvents: [
                ['$ai_metric', { $ai_metric_value: 'bad' }],
                ['$ai_feedback', { $ai_feedback_text: 'Too long' }],
                ['posthog ai feedback dialog closed', { outcome: 'submitted', has_text: true }],
            ],
            toast: true,
        },
        {
            name: 'cancelling with a draft',
            typed: 'Half a thought',
            close: 'cancel',
            expectedEvents: [
                ['$ai_metric', { $ai_metric_value: 'bad' }],
                ['posthog ai feedback dialog closed', { outcome: 'cancelled', has_text: true }],
            ],
            toast: false,
        },
    ])('$name keeps the rating and never reopens the dialog', async ({ typed, close, expectedEvents, toast }) => {
        const { container } = render(
            <TurnFeedbackActions sessionId="session-1" turnIndex={2} run={{}} traceId="trace-1" turnText="Answer" />
        )
        const thumbsDown = (): Element => container.querySelector('[data-attr="posthog-ai-turn-rating-bad"]')!

        fireEvent.click(thumbsDown())
        expect(screen.getByText('Share feedback')).toBeInTheDocument()

        const textArea = screen.getByPlaceholderText('Help us improve PostHog AI…')
        fireEvent.change(textArea, { target: { value: typed } })
        if (close === 'shortcut') {
            fireEvent.keyDown(textArea, { key: 'Enter', metaKey: true })
        } else {
            // A double click lands while the dialog is still closing, and must not send twice.
            fireEvent.click(screen.getByText(close === 'submit' ? 'Submit' : 'Cancel'))
            fireEvent.click(screen.getByText(close === 'submit' ? 'Submit' : 'Cancel'))
        }
        await waitFor(() => expect(screen.queryByText('Share feedback')).not.toBeInTheDocument())

        fireEvent.click(thumbsDown())
        expect(screen.queryByText('Share feedback')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="posthog-ai-turn-rating-good"]')).toBeNull()

        expect(captureSpy.mock.calls.map(([event, properties]) => [event, properties])).toEqual(
            expectedEvents.map(([event, properties]) => [event, expect.objectContaining(properties)])
        )
        expect(toastSpy).toHaveBeenCalledTimes(toast ? 1 : 0)
    })
})
