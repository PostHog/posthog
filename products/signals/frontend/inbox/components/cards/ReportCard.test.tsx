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
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        implementation_pr_state: null,
        work_state: 'unclaimed',
        assignee: null,
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

    it.each([
        [
            'an external claim',
            {
                work_state: 'working' as const,
                assignee: {
                    kind: 'agent' as const,
                    user: {
                        id: 1,
                        uuid: 'user-1',
                        first_name: 'Mikayla',
                        last_name: 'Thompson',
                        email: 'mikayla@example.com',
                    },
                    task_id: null,
                    agent: 'Codex',
                    claimed_at: '2026-09-04T12:00:00Z',
                },
            },
            "In progress by Mikayla's Codex",
        ],
        [
            'an external pull request',
            {
                implementation_pr_url: 'https://github.com/PiedPiper/pipernet/pull/486',
                implementation_pr_state: 'open' as const,
                work_state: 'in_review' as const,
                assignee: {
                    kind: 'agent' as const,
                    user: {
                        id: 1,
                        uuid: 'user-1',
                        first_name: 'Mikayla',
                        last_name: 'Thompson',
                        email: 'mikayla@example.com',
                    },
                    task_id: null,
                    agent: 'Codex',
                    claimed_at: '2026-09-04T12:00:00Z',
                },
            },
            "External PR by Mikayla's Codex",
        ],
        [
            'a PostHog pull request',
            {
                implementation_pr_url: 'https://github.com/PostHog/posthog/pull/486',
                implementation_pr_state: 'open' as const,
                work_state: 'in_review' as const,
                assignee: {
                    kind: 'task' as const,
                    user: null,
                    task_id: '019e64b8-0000-7000-8000-000000000001',
                    agent: null,
                    claimed_at: '2026-09-04T12:00:00Z',
                },
            },
            'PR by PostHog agent',
        ],
    ])('shows %s', (_case, overrides, label) => {
        const { getByText } = render(<ReportCard report={makeReport(overrides)} />)

        expect(getByText(label)).toBeInTheDocument()
    })

    it('uses the attached pull request state even before the report status catches up', () => {
        const { getByLabelText } = render(
            <ReportCard
                report={makeReport({
                    implementation_pr_url: 'https://github.com/PiedPiper/pipernet/pull/486',
                    implementation_pr_state: 'closed',
                })}
            />
        )

        expect(getByLabelText('Open pull request #486 (Closed) on GitHub')).toBeInTheDocument()
    })
})
