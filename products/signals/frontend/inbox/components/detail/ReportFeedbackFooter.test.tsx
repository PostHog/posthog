import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { captureInboxReportFeedback, captureInboxReportFeedbackNote } from '../../inboxAnalytics'
import { CELEBRATION_DURATION_MS } from './ReportFeedbackCelebration'
import { ReportFeedbackFooter } from './ReportFeedbackFooter'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportFeedback: jest.fn(),
    captureInboxReportFeedbackNote: jest.fn(),
}))

const CELEBRATION_SELECTOR = '[data-attr="inbox-report-feedback-celebration"]'

function setCelebrationFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG], {
        [FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG]: enabled,
    })
}

function setReducedMotion(matches: boolean): void {
    jest.mocked(window.matchMedia).mockImplementation(
        (query: string) =>
            ({
                matches: query.includes('prefers-reduced-motion') && matches,
                media: query,
                onchange: null,
                addListener: jest.fn(),
                removeListener: jest.fn(),
                addEventListener: jest.fn(),
                removeEventListener: jest.fn(),
                dispatchEvent: jest.fn(),
            }) as MediaQueryList
    )
}

describe('ReportFeedbackFooter', () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })

    beforeEach(async () => {
        jest.useFakeTimers()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/feedback_state/': { sentiment: null, note: '' },
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/feedback/': [200, { forwarded: false }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        setReducedMotion(false)
        jest.mocked(captureInboxReportFeedback).mockClear()
        jest.mocked(captureInboxReportFeedbackNote).mockClear()
        render(<ReportFeedbackFooter report={makeReport({ id: 'report-celebration' })} />)
        await waitFor(() =>
            expect(screen.getByLabelText('This report was useful')).toHaveAttribute('aria-disabled', 'false')
        )
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('pops the hog once on thumbs-up and removes it when the animation ends', async () => {
        setCelebrationFlag(true)
        const thumbsUp = screen.getByLabelText('This report was useful')

        await user.click(thumbsUp)

        await waitFor(() => expect(document.querySelector(CELEBRATION_SELECTOR)).toBeInTheDocument())
        await waitFor(() => expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1))
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'positive' }))

        act(() => {
            jest.advanceTimersByTime(CELEBRATION_DURATION_MS)
        })
        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()

        // Clearing the rating does not start the animation.
        await user.click(thumbsUp)
        await waitFor(() => expect(thumbsUp).toHaveAttribute('aria-pressed', 'false'))
        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })

    it('asks a question matched to the rating, sends the note with Enter, and shows what went through', async () => {
        setCelebrationFlag(false)
        expect(screen.queryByLabelText('Add a note about this report')).not.toBeInTheDocument()

        await user.click(screen.getByLabelText('This report was useful'))
        expect(await screen.findByText('What made it useful?')).toBeVisible()

        await user.click(screen.getByLabelText('This report was not useful'))
        expect(await screen.findByText('What was off?')).toBeVisible()
        let finishRequest!: () => void
        const responseReady = new Promise<void>((resolve) => {
            finishRequest = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/feedback/': async () => {
                    await responseReady
                    return [200, { forwarded: false }]
                },
            },
        })
        const note = screen.getByLabelText('Add a note about this report')
        await user.type(note, 'The repro steps were wrong{Enter}')
        await waitFor(() => expect(note).toBeDisabled())
        await user.type(note, 'More text')
        expect(note).toHaveValue('The repro steps were wrong')
        finishRequest()

        await waitFor(() =>
            expect(captureInboxReportFeedbackNote).toHaveBeenCalledWith(
                expect.objectContaining({ sentiment: 'negative', note: 'The repro steps were wrong' })
            )
        )
        expect(await screen.findByText('Note added: The repro steps were wrong')).toBeVisible()
        expect(screen.queryByLabelText('Add a note about this report')).not.toBeInTheDocument()
    })

    it('does not pop on thumbs-down', async () => {
        setCelebrationFlag(true)

        await user.click(screen.getByLabelText('This report was not useful'))

        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        await waitFor(() =>
            expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'negative' }))
        )
    })

    it.each([
        ['the flag is off', false, false],
        ['the reader prefers reduced motion', true, true],
    ])('records the rating without a pop when %s', async (_, flagEnabled, reducedMotion) => {
        setCelebrationFlag(flagEnabled)
        setReducedMotion(reducedMotion)

        await user.click(screen.getByLabelText('This report was useful'))

        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        await waitFor(() =>
            expect(screen.getByLabelText('This report was useful')).toHaveAttribute('aria-pressed', 'true')
        )
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })
})
