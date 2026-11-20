import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import type {
    LinkedReportRefApi,
    LinkPlanSummaryApi,
    ReportLinkSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import { makeReport } from '../../__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from '../../types'
import { ReportCard } from './ReportCard'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Cards/Link strip',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11T00:00:00Z',
        featureFlags: [FEATURE_FLAGS.INBOX_CARDS_LINK_RELATED_REPORTS],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj

const pullRequest = (number: number): string => `https://github.com/example/repo/pull/${number}`

function linkedReport(
    id: string,
    title: string,
    status: SignalReportStatus,
    prNumber: number | null = null,
    prState: LinkedReportRefApi['implementation_pr_state'] = null
): LinkedReportRefApi {
    return {
        id,
        title,
        status,
        implementation_pr_url: prNumber ? pullRequest(prNumber) : null,
        implementation_pr_state: prState,
    }
}

const exportsPlan: LinkPlanSummaryApi = {
    id: 'plan-exports',
    title: 'Stop funnel exports timing out on large projects',
    steps: [
        { id: 'layer-1', title: 'Move the funnel export query into a paged runner', state: 'in_review' },
        { id: 'layer-2', title: 'Stream export pages to object storage', state: 'waiting' },
        { id: 'layer-3', title: 'Show export progress in the exports list', state: 'waiting' },
    ],
    lead_step_id: 'layer-1',
}

const cohortPlan: LinkPlanSummaryApi = {
    id: 'plan-cohorts',
    title: 'Retire the legacy cohort membership table',
    steps: [
        { id: 'cohort-1', title: 'Dual-write cohort membership', state: 'merged' },
        { id: 'cohort-2', title: 'Backfill the new membership table', state: 'merged' },
        { id: 'cohort-3', title: 'Read cohort sizes from the new table', state: 'in_review' },
        { id: 'cohort-4', title: 'Read feature flag cohorts from the new table', state: 'waiting' },
        { id: 'cohort-5', title: 'Read insight filters from the new table', state: 'waiting' },
        { id: 'cohort-6', title: 'Stop writing the legacy table', state: 'waiting' },
        { id: 'cohort-7', title: 'Drop legacy reads from exports', state: 'waiting' },
        { id: 'cohort-8', title: 'Drop the legacy table', state: 'waiting' },
    ],
    lead_step_id: 'cohort-3',
}

function linkSummary(overrides: Partial<ReportLinkSummaryApi>): ReportLinkSummaryApi {
    return { kind: 'part_of', report: null, plan: null, other_links: [], ...overrides }
}

// One card per strip kind, the Monitoring band and the strip on one card, an eight-layer plan, and a plan
// shown on its own because none of its layers is in the list.
const linkedReports: SignalReport[] = [
    makeReport({
        id: 'layer-1',
        title: 'refactor(exports): Move the funnel export query into a paged runner',
        summary: 'No behavior change. Splits the single export query into keyset pages that the later layers build on.',
        priority: 'P1',
        implementation_pr_url: pullRequest(4812),
        implementation_pr_state: 'open',
        source_products: ['error_tracking', 'logs', 'session_replay'],
        updated_at: '2026-06-10T09:25:00Z',
        link_summary: linkSummary({ kind: 'part_of', plan: exportsPlan }),
    }),
    makeReport({
        title: 'fix(billing): Usage emails send twice when the job retries',
        summary:
            'Two customers got the monthly usage email twice. The retry runs before the first send is marked done.',
        priority: 'P1',
        source_products: ['conversations'],
        updated_at: '2026-06-10T09:40:00Z',
        link_summary: linkSummary({
            kind: 'recurrence_of',
            report: linkedReport(
                'old-usage',
                'Duplicate usage emails after billing job restarts',
                SignalReportStatus.RESOLVED,
                4690,
                'merged'
            ),
            other_links: [
                {
                    kind: 'depends_on',
                    report: linkedReport(
                        'lock',
                        'Hold a lock while the billing job sends emails',
                        SignalReportStatus.READY
                    ),
                },
            ],
        }),
    }),
    makeReport({
        title: 'perf(replay): Recording list loads slowly after the pagination change',
        summary: 'The follow-up check on the pagination fix failed on day 4. Load time is back above 3 seconds.',
        priority: 'P2',
        updated_at: '2026-06-10T07:10:00Z',
        link_summary: linkSummary({
            kind: 'follow_up_of',
            report: linkedReport(
                'slow-recordings',
                'Recording list is slow to load for large projects',
                SignalReportStatus.RESOLVED,
                4702,
                'merged'
            ),
        }),
    }),
    makeReport({
        title: 'perf(insights): Retention insight is slow with a relative date range',
        summary: 'Retention insights with "last 90 days" take over 20 seconds to load.',
        priority: 'P2',
        source_products: ['logs'],
        updated_at: '2026-06-10T05:00:00Z',
        link_summary: linkSummary({
            kind: 'duplicate_of',
            report: linkedReport(
                'retention-scan',
                'Retention query scans every partition for relative ranges',
                SignalReportStatus.READY,
                4790,
                'open'
            ),
        }),
    }),
    makeReport({
        title: 'feat(flags): Show evaluation reasons in the flag debugger',
        summary: 'People debugging a flag cannot see why it evaluated to false for a given person.',
        priority: 'P3',
        source_products: ['github'],
        updated_at: '2026-06-09T16:00:00Z',
        link_summary: linkSummary({
            kind: 'depends_on',
            report: linkedReport(
                'flag-reasons',
                'Record evaluation reasons on the flag called event',
                SignalReportStatus.READY,
                4801,
                'draft'
            ),
        }),
    }),
    makeReport({
        id: 'cohort-2',
        title: 'chore(cohorts): Backfill the new membership table',
        summary: 'Copies every static and dynamic cohort membership into the new table in batches.',
        priority: 'P2',
        status: SignalReportStatus.MONITORING,
        implementation_pr_url: pullRequest(4776),
        implementation_pr_merged: true,
        monitoring_started_at: '2026-06-10T20:00:00Z',
        monitoring_summary: {
            state: 'final_check_only',
            started_at: '2026-06-10T20:00:00Z',
            ends_at: '2026-06-13T20:00:00Z',
            lead_check: null,
            checks: [],
        },
        link_summary: linkSummary({ kind: 'part_of', plan: cohortPlan }),
    }),
    makeReport({
        id: 'plan-exports',
        title: 'fix(exports): Stop funnel exports timing out on large projects',
        summary: 'Funnel exports for projects with more than 10M events time out after 10 minutes.',
        priority: 'P1',
        source_products: ['error_tracking'],
        updated_at: '2026-06-10T08:00:00Z',
        link_summary: linkSummary({ kind: 'plan', plan: exportsPlan }),
    }),
]

export const LinkStrips: Story = {
    render: () => (
        <div className="bg-primary min-h-screen mx-auto max-w-4xl px-6 py-6">
            <div className="@container flex flex-col gap-1.5">
                {linkedReports.map((report) => (
                    <ReportCard key={report.id} report={report} selectable />
                ))}
            </div>
        </div>
    ),
}

/** At phone width each strip wraps to two lines: the relationship and title, then the state and controls. */
export const LinkStripsNarrow: Story = {
    render: () => (
        <div className="bg-primary min-h-screen w-[390px] px-3 py-6">
            <div className="@container flex flex-col gap-1.5">
                {linkedReports.map((report) => (
                    <ReportCard key={report.id} report={report} selectable />
                ))}
            </div>
        </div>
    ),
}
