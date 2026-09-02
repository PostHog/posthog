import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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

    // The redesign makes the linked row the only way in and leaves the status / actionability chips
    // to the section headers; the legacy list keeps Dismiss, the Review button, and the chips.
    it.each([[true], [false]])(
        'with the redesign flag %p shows Review and Dismiss and chips only on the legacy list',
        (redesign) => {
            const legacyChrome = !redesign
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
                [FEATURE_FLAGS.INBOX_REDESIGN]: redesign,
            })
            const report = makeReport({
                status: SignalReportStatus.CANDIDATE,
                actionability: 'immediately_actionable',
            })
            const { queryByText } = render(<ReportCard report={report} />)
            expect(queryByText('Review') !== null).toBe(legacyChrome)
            expect(queryByText('View report')).toBeNull()
            expect(queryByText('Dismiss') !== null).toBe(legacyChrome)
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

    it('shows the affected-user snapshot in a redesigned row and prefers it over the primary metric', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        })
        const user = userEvent.setup()
        const report = makeReport({
            metrics: [
                {
                    metric_id: 'conversion',
                    title: 'Conversion rate',
                    kind: 'conversion_rate',
                    role: 'primary',
                    value: 34,
                    value_at: null,
                    value_format: 'percentage',
                    unit: null,
                    caption: null,
                },
                {
                    metric_id: 'affected-users',
                    title: 'Users affected',
                    kind: 'affected_users',
                    role: 'supporting',
                    value: 42,
                    value_at: '2026-08-28T12:00:00Z',
                    value_format: 'count',
                    unit: 'users',
                    caption: null,
                },
            ],
        })

        render(<ReportCard report={report} />)

        expect(screen.getByText('42 users')).toBeInTheDocument()
        expect(screen.getByText('Users affected')).toBeInTheDocument()
        expect(screen.queryByText('34%')).not.toBeInTheDocument()

        await user.hover(screen.getByText('42 users'))
        expect(await screen.findByText('2026-08-28T12:00:00Z')).toBeInTheDocument()
    })

    it('uses the primary snapshot when there is no affected-user snapshot', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        })
        const report = makeReport({
            metrics: [
                {
                    metric_id: 'conversion',
                    title: 'Conversion rate',
                    kind: 'conversion_rate',
                    role: 'primary',
                    value: 34,
                    value_at: null,
                    value_format: 'percentage',
                    unit: null,
                    caption: null,
                },
            ],
        })

        const { container } = render(<ReportCard report={report} />)

        expect(screen.getByText('34%')).toBeInTheDocument()
        expect(screen.getByText('Conversion rate')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).not.toBeNull()
    })

    it('does not show a list metric without a stored snapshot or under the legacy design', () => {
        const report = makeReport({
            metrics: [
                {
                    metric_id: 'affected-users',
                    title: 'Users affected',
                    kind: 'affected_users',
                    role: 'primary',
                    value: null,
                    value_at: null,
                    value_format: 'count',
                    unit: 'users',
                    caption: null,
                },
            ],
        })

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        })
        const { container, rerender } = render(<ReportCard report={report} />)
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: false,
        })
        rerender(
            <ReportCard
                report={makeReport({
                    metrics: [{ ...report.metrics![0], value: 42 }],
                })}
            />
        )
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()
    })
})
