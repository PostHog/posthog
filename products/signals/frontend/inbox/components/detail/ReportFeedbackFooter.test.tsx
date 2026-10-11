import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { captureInboxReportFeedback } from '../../inboxAnalytics'
import { BANG_DURATION_MS } from './ReportFeedbackBang'
import { ReportFeedbackFooter } from './ReportFeedbackFooter'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportFeedback: jest.fn(),
}))

const BANG_SELECTOR = '[data-attr="inbox-report-feedback-bang"]'

function setBangFlag(enabled: boolean): void {
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
        render(<ReportFeedbackFooter report={makeReport({ id: 'report-bang' })} />)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('pops the burst once on thumbs-up and removes it when the animation ends', async () => {
        setBangFlag(true)
        const thumbsUp = screen.getByLabelText('This report was useful')

        await user.click(thumbsUp)

        expect(document.querySelector(BANG_SELECTOR)).toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'positive' }))

        act(() => {
            jest.advanceTimersByTime(BANG_DURATION_MS)
        })
        expect(document.querySelector(BANG_SELECTOR)).not.toBeInTheDocument()

        // A re-click is a no-op for feedback, so it earns no second burst either.
        await user.click(thumbsUp)
        expect(document.querySelector(BANG_SELECTOR)).not.toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })

    it('does not pop on thumbs-down', async () => {
        setBangFlag(true)

        await user.click(screen.getByLabelText('This report was not useful'))

        expect(document.querySelector(BANG_SELECTOR)).not.toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(expect.objectContaining({ sentiment: 'negative' }))
    })

    it.each([
        ['the flag is off', false, false],
        ['the reader prefers reduced motion', true, true],
    ])('records the rating without a burst when %s', async (_, flagEnabled, reducedMotion) => {
        setBangFlag(flagEnabled)
        setReducedMotion(reducedMotion)

        await user.click(screen.getByLabelText('This report was useful'))

        expect(document.querySelector(BANG_SELECTOR)).not.toBeInTheDocument()
        expect(screen.getByText('Thanks for the feedback')).toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
    })
})
