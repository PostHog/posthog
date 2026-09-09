import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { NodeKind, type InsightVizNode, type TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { makeReport, pullRequestReports, reportTabReports, runReportsMany } from '../../__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from '../../types'
import { AgentRunCard } from './AgentRunCard'
import { CardSkeleton } from './CardSkeleton'
import { ReportCard } from './ReportCard'

// Individual card stories across every state, so card design / badges / right-rail
// density can be polished in isolation against the desktop equivalents.

const meta: Meta = {
    title: 'Scenes-App/Inbox/Cards',
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2026-06-11' },
}
export default meta

type Story = StoryObj

function Stack({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="bg-primary min-h-screen mx-auto max-w-4xl px-6 py-6 flex flex-col gap-3">{children}</div>
}

export const ReportCards: Story = {
    render: () => (
        <Stack>
            {reportTabReports.map((r) => (
                <ReportCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

/** The inbox list's own frame: a container-query scope at the list's width and row spacing. */
function CardList({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="bg-primary min-h-screen mx-auto max-w-4xl px-6 py-6">
            <div className="@container flex flex-col gap-1.5">{children}</div>
        </div>
    )
}

function metricQuery(
    event: string,
    customName: string,
    math: BaseMathType = BaseMathType.TotalCount
): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            dateRange: { date_from: '-14d', date_to: null },
            interval: 'day',
            series: [{ kind: NodeKind.EventsNode, event, name: event, custom_name: customName, math }],
            trendsFilter: { display: ChartDisplayType.ActionsBar },
        },
    }
}

// One row per figure shape the impact column has to line up: a rising count, a flat count, a rate, a
// scaled rate, a duration with no strip, and a report with no figure at all.
const impactReports: SignalReport[] = [
    makeReport({
        title: "fix(max): Stop 'Conversation not found' on AI chat deep links",
        summary:
            'Opening a shared AI chat link lands on a "Conversation not found" page. The thread exists, but the deep link resolves before the conversation is fetched.',
        priority: 'P1',
        source_products: ['session_replay'],
        created_at: '2026-06-02T08:00:00Z',
        updated_at: '2026-06-09T14:20:00Z',
        metrics: [
            {
                metric_id: 'affected-users',
                title: 'People who hit the not-found page',
                kind: 'affected_users',
                role: 'primary',
                value: 237,
                value_at: '2026-06-09T14:00:00Z',
                series: [4, 5, 6, 5, 8, 9, 12, 14, 16, 19, 22, 25, 28, 31],
                value_format: 'count',
                unit: 'users',
                query: metricQuery('conversation_not_found', 'People affected', BaseMathType.UniqueUsers),
                caption: null,
            },
        ],
    }),
    makeReport({
        title: "fix(max): Don't report the 2FA gate as an exception",
        summary:
            'Every sign-in that stops at the two-factor prompt raises an exception. The gate works as designed, so the volume buries real errors.',
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-04T11:30:00Z',
        updated_at: '2026-06-10T07:45:00Z',
        metrics: [
            {
                metric_id: 'occurrences',
                title: 'Exceptions raised by the 2FA gate',
                kind: 'occurrences',
                role: 'primary',
                value: 3758,
                value_at: '2026-06-10T07:00:00Z',
                series: [260, 270, 255, 280, 265, 275, 270, 262, 268, 258, 272, 266, 271, 269],
                value_format: 'count',
                unit: null,
                query: metricQuery('$exception', 'Exceptions'),
                caption: null,
            },
        ],
    }),
    makeReport({
        title: 'fix(signals): Stop the inbox Ask AI button failing two attempts in five',
        summary:
            'Asking a question from a report fails about two times in five. The request times out before the first token arrives, and the box clears itself.',
        priority: 'P1',
        source_products: ['llm_analytics'],
        created_at: '2026-06-05T16:10:00Z',
        updated_at: '2026-06-10T18:05:00Z',
        metrics: [
            {
                metric_id: 'error-rate',
                title: 'Share of Ask AI attempts that fail',
                kind: 'error_rate',
                role: 'primary',
                value: 40,
                value_at: '2026-06-10T18:00:00Z',
                series: [35, 42, 38, 44, 39, 41, 37, 43, 40, 38, 45, 39, 42, 40],
                value_format: 'percentage',
                unit: 'failure',
                query: metricQuery('ask_ai_failed', 'Failed attempts'),
                caption: null,
            },
        ],
    }),
    makeReport({
        title: 'feat(signals): Add a manual setup path to the inbox takeover',
        summary:
            'People who cannot install the agent leave the takeover screen with nothing to do. A manual path would let them finish setup by hand.',
        priority: 'P2',
        source_products: ['session_replay'],
        created_at: '2026-05-29T09:00:00Z',
        updated_at: '2026-06-09T21:15:00Z',
        metrics: [
            {
                metric_id: 'conversion-rate',
                title: 'Takeover screens that end in a finished setup',
                kind: 'conversion_rate',
                role: 'primary',
                value: 0.051,
                value_at: '2026-06-09T21:00:00Z',
                series: [5, 6, 4, 5, 5, 6, 5, 4, 5, 5, 6, 5, 5, 5],
                value_format: 'percentage_scaled',
                unit: null,
                query: metricQuery('inbox_setup_finished', 'Finished setup', BaseMathType.UniqueUsers),
                caption: null,
            },
        ],
    }),
    makeReport({
        title: 'perf(ci): Land the stalled Depot and cache fix for CI CLI',
        summary: 'The CLI job spends most of its run rebuilding a cache that a merged fix already avoids.',
        priority: 'P3',
        source_products: ['github'],
        implementation_pr_url: 'https://github.com/example/repo/pull/86709',
        created_at: '2026-06-01T13:00:00Z',
        updated_at: '2026-06-10T10:30:00Z',
        metrics: [
            {
                metric_id: 'job-duration',
                title: 'Median CI CLI job duration',
                kind: 'duration',
                role: 'primary',
                value: 287,
                value_at: '2026-06-10T10:00:00Z',
                series: null,
                value_format: 'duration',
                unit: 's',
                query: metricQuery('ci_job_finished', 'CI CLI job'),
                caption: null,
            },
        ],
    }),
    makeReport({
        title: "fix(posthog-ai): Stop sending users to a Help label that doesn't exist",
        summary:
            'The answer points at a "Help" menu entry that was renamed, so people look for a label that is not there.',
        priority: 'P2',
        source_products: ['llm_analytics'],
        created_at: '2026-06-06T12:00:00Z',
        updated_at: '2026-06-10T16:40:00Z',
        metrics: [],
    }),
]

export const ReportCardWithImpact: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.INBOX_REDESIGN] },
    render: () => (
        <CardList>
            {impactReports.map((report) => (
                <ReportCard key={report.id} report={report} />
            ))}
        </CardList>
    ),
}

export const PullRequestCards: Story = {
    render: () => (
        <Stack>
            {pullRequestReports.map((r) => (
                <ReportCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

export const AgentRunCards: Story = {
    render: () => (
        <Stack>
            {runReportsMany.map((r) => (
                <AgentRunCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

export const ReportCardStates: Story = {
    render: () => (
        <Stack>
            <ReportCard
                report={makeReport({
                    title: 'P0 critical, immediately actionable',
                    priority: 'P0',
                    actionability: 'immediately_actionable',
                    source_products: ['error_tracking'],
                    is_suggested_reviewer: true,
                    summary: 'Highest severity, clean fix available.',
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'Requires human input',
                    priority: 'P2',
                    actionability: 'requires_human_input',
                    source_products: ['session_replay', 'zendesk'],
                    summary: 'Needs a product call before an agent can proceed.',
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'No summary yet, still collecting context',
                    status: SignalReportStatus.CANDIDATE,
                    priority: null,
                    actionability: null,
                    summary: null,
                    source_products: ['llm_analytics'],
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'Not actionable, low priority',
                    priority: 'P4',
                    actionability: 'not_actionable',
                    source_products: ['github'],
                    summary: 'Real but insignificant.',
                })}
            />
            {/* Closed states keep the open-row surface, dimmed; a green or red dot on the reason tag says which. */}
            <ReportCard
                report={makeReport({
                    title: 'Resolved by a merged pull request',
                    priority: 'P1',
                    status: SignalReportStatus.RESOLVED,
                    dismissal_reason: 'pr_merged',
                    source_products: ['error_tracking'],
                    summary: 'Fixed and shipped; kept for reference.',
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'Dismissed as intentional behavior',
                    priority: 'P3',
                    status: SignalReportStatus.SUPPRESSED,
                    dismissal_reason: 'wontfix_intentional',
                    source_products: ['session_replay'],
                    summary: 'The flow works as designed.',
                })}
            />
        </Stack>
    ),
}

export const Skeleton: Story = {
    // Skeletons render permanently, so the VR runner must not wait for loaders to disappear.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    render: () => (
        <Stack>
            {/* Dashed report/not-actionable card skeletons, then solid PR card skeletons – matching the live tabs. */}
            <CardSkeleton count={3} variant="cards" />
            <CardSkeleton count={2} variant="cards" dashed={false} />
        </Stack>
    ),
}
