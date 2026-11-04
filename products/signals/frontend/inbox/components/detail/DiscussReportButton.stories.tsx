import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'

import { SidePanelMax } from '~/layout/navigation-3000/sidepanel/panels/max/SidePanelMax'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { mswDecorator } from '~/mocks/browser'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'
import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { makeReport } from '../../__mocks__/inboxMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { DiscussReportButton } from './DiscussReportButton'
import { ReportCheckRow } from './ReportCheckRow'
import { ReportDiscussionComposer } from './ReportDiscussionComposer'

const report = makeReport({
    title: 'Exceptions increased after a release',
    suggested_prompts: [
        'Which pages have the most exceptions?',
        'Did the error rate change after the release?',
        'Add the missing null check and open a pull request',
    ],
})

const meta: Meta<typeof ReportDiscussionComposer> = {
    title: 'Scenes-App/Inbox/DiscussReportButton',
    component: ReportDiscussionComposer,
    parameters: { layout: 'centered' },
    decorators: [
        function ReportContext(Story, context): JSX.Element {
            useAttachedContext([{ type: 'inbox_report', key: report.id, label: `Report: ${report.title}` }])
            return (
                <div
                    className={
                        context.name === 'Sidebar' || context.name === 'Metric suggestion'
                            ? 'w-[960px] max-w-[calc(100vw-2rem)]'
                            : 'w-96 max-w-full'
                    }
                >
                    <Story />
                </div>
            )
        },
    ],
    args: { report, reportUrl: 'https://example.com/project/1/inbox/report-1' },
}
export default meta

type Story = StoryObj<typeof ReportDiscussionComposer>

export const WithSuggestions: Story = {}

export const WithoutSuggestions: Story = {
    args: { report: { ...report, suggested_prompts: [] } },
}

export const Sidebar: Story = {
    render: function Sidebar(): JSX.Element {
        const { sidePanelOpen } = useValues(sidePanelStateLogic)
        return (
            <div className="flex h-[650px] border border-primary rounded overflow-hidden">
                <div className="flex-1 min-w-0 p-4">
                    <h2>{report.title}</h2>
                    <p>A null value causes an exception when a user submits the form.</p>
                    <DiscussReportButton report={report} reportUrl="https://example.com/project/1/inbox/report-1" />
                </div>
                {sidePanelOpen && (
                    <div className="flex flex-col w-96 min-w-0 border-l border-primary">
                        <Suspense fallback={<Spinner />}>
                            <SidePanelMax />
                        </Suspense>
                    </div>
                )}
            </div>
        )
    },
}

export const MetricSuggestion: Story = {
    name: 'Metric suggestion',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
                '/api/projects/:team_id/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: {} },
            },
            post: { '/api/projects/:team_id/tasks/warm/': {} },
        }),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE],
        testOptions: { snapshotBrowsers: [] },
    },
    render: function MetricSuggestion(): JSX.Element {
        const { sidePanelOpen } = useValues(sidePanelStateLogic)
        const { openReportCheckMetricSuggestion } = useActions(inboxTaskKickoffLogic)
        const check = {
            id: 'checkout-check',
            title: 'Checkout errors stay low after the retry fix',
            kind: 'agent',
            status: 'pending',
        } as SignalReportCheckApi
        return (
            <div className="flex h-[650px] border border-primary rounded overflow-hidden">
                <div className="flex-1 min-w-0 p-4">
                    <h2>{report.title}</h2>
                    <ReportCheckRow
                        row={{
                            check,
                            reportStatus: 'ready',
                            tag: { label: 'Paused', type: 'muted' },
                            detail: 'Checks run only while this report is in Monitoring.',
                            cancelled: false,
                            cancellable: true,
                        }}
                        cancelling={false}
                        onCancel={() => undefined}
                        onSuggestMetric={() => openReportCheckMetricSuggestion(report, check)}
                    />
                </div>
                {sidePanelOpen && (
                    <div className="flex flex-col w-96 min-w-0 border-l border-primary">
                        <Suspense fallback={<Spinner />}>
                            <SidePanelMax />
                        </Suspense>
                    </div>
                )}
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(canvas.getByText('Suggest a better metric'))
        await waitFor(
            () => {
                const input = canvas.getByRole('textbox') as HTMLTextAreaElement
                if (!input.value.includes('check ID: checkout-check')) {
                    throw new Error('The selected check is missing from the prompt')
                }
            },
            { timeout: 10000 }
        )
    },
}

async function openQuickAsk(canvasElement: HTMLElement): Promise<void> {
    await userEvent.click(await within(canvasElement).findByLabelText('Quick ask and more AI actions'))
    await waitFor(() => {
        if (!document.querySelector('.Popover')) {
            throw new Error('quick ask not open yet')
        }
    })
}

export const QuickAskWithSuggestions: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => <DiscussReportButton report={report} reportUrl="https://example.com/project/1/inbox/report-1" />,
    play: async ({ canvasElement }) => openQuickAsk(canvasElement),
}

export const QuickAskWithoutSuggestions: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => (
        <DiscussReportButton
            report={{ ...report, suggested_prompts: [] }}
            reportUrl="https://example.com/project/1/inbox/report-1"
        />
    ),
    play: async ({ canvasElement }) => openQuickAsk(canvasElement),
}
