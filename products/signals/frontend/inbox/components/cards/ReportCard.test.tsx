import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../../types'
import { ReportCard } from './ReportCard'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: 'report-1',
        title: 'Hooli traffic is hammering the beta',
        summary: 'Sign-ups from Hooli IP ranges jumped overnight.',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        ...overrides,
    } as SignalReport
}

describe('ReportCard', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })
    afterEach(cleanup)

    // The redesign gives a row one action and leaves the status / actionability chips to the section
    // headers; the legacy list keeps Archive, the "Review" label, and the chips.
    it.each([
        [true, 'View report', false],
        [false, 'Review', true],
    ])(
        'with the redesign flag %p shows %p and archive=chips=%p on a report without a PR',
        (redesign, label, legacyChrome) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
                [FEATURE_FLAGS.INBOX_REDESIGN]: redesign,
            })
            const report = makeReport({
                status: SignalReportStatus.CANDIDATE,
                actionability: 'immediately_actionable',
            })
            const { getByText, queryByText } = render(<ReportCard report={report} />)
            expect(getByText(label)).toBeInTheDocument()
            expect(queryByText('Archive') !== null).toBe(legacyChrome)
            expect(queryByText('Queued') !== null).toBe(legacyChrome)
            expect(queryByText('Actionable') !== null).toBe(legacyChrome)
        }
    )

    it('links the card to the report detail by default', () => {
        const { container } = render(<ReportCard report={makeReport()} />)
        expect(container.querySelector('a')).toHaveAttribute('href', expect.stringContaining('report-1'))
    })

    it('exposes no routable link in preview mode (the placeholder id 404s)', () => {
        const { container, getByText } = render(<ReportCard report={makeReport()} preview />)
        // Card still renders, but nothing navigates to the detail route.
        expect(getByText('Hooli traffic is hammering the beta')).toBeInTheDocument()
        expect(container.querySelector('a')).toBeNull()
    })

    it('exposes no link on a preview PR card either (the PR badge url is fabricated)', () => {
        const report = makeReport({
            title: 'fix(compression): stop 4K streams dropping to single-threaded encode',
            implementation_pr_url: 'https://github.com/PiedPiper/pipernet/pull/486',
        })
        const { container } = render(<ReportCard report={report} preview />)
        expect(container.querySelector('a')).toBeNull()
    })
})
