import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
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

    beforeEach(() => {
        jest.useFakeTimers()
        useMocks({
            get: {
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
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('pops the hog once on thumbs-up and removes it when the animation ends', async () => {
        setCelebrationFlag(true)
        const thumbsUp = screen.getByLabelText('This report was useful')

        await user.click(thumbsUp)

        expect(document.querySelector(CELEBRATION_SELECTOR)).toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'positive' }))

        act(() => {
            jest.advanceTimersByTime(CELEBRATION_DURATION_MS)
        })
        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()

        // A re-click is a no-op for feedback, so it earns no second pop either.
        await user.click(thumbsUp)
        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })

    it('asks a question matched to the rating, sends the note with Enter, and shows what went through', async () => {
        setCelebrationFlag(false)
        expect(screen.queryByLabelText('Add a note about this report')).not.toBeInTheDocument()

        await user.click(screen.getByLabelText('This report was useful'))
        expect(screen.getByText('What made it useful?')).toBeVisible()

        await user.click(screen.getByLabelText('This report was not useful'))
        expect(screen.getByText('What was off?')).toBeVisible()
        await user.type(screen.getByLabelText('Add a note about this report'), 'The repro steps were wrong{Enter}')

        expect(captureInboxReportFeedbackNote).toHaveBeenCalledWith(
            expect.objectContaining({ sentiment: 'negative', note: 'The repro steps were wrong' })
        )
        expect(screen.getByText('Note added: The repro steps were wrong')).toBeVisible()
        expect(screen.queryByLabelText('Add a note about this report')).not.toBeInTheDocument()
    })

    it('does not pop on thumbs-down', async () => {
        setCelebrationFlag(true)

        await user.click(screen.getByLabelText('This report was not useful'))

        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'negative' }))
    })

    it.each([
        ['the flag is off', false, false],
        ['the reader prefers reduced motion', true, true],
    ])('records the rating without a pop when %s', async (_, flagEnabled, reducedMotion) => {
        setCelebrationFlag(flagEnabled)
        setReducedMotion(reducedMotion)

        await user.click(screen.getByLabelText('This report was useful'))

        expect(document.querySelector(CELEBRATION_SELECTOR)).not.toBeInTheDocument()
        expect(screen.getByText('Thanks for the feedback!')).toBeVisible()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })
})
