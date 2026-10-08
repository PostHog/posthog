import { Meta, StoryObj } from '@storybook/react'

import { IconCalendar, IconPlus, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotificationSlackPreview } from 'scenes/hog-functions/sub-templates/NotificationSlackPreview'

import { NotificationTypeRow, NotificationTypesTable } from './NotificationTypesTable'
import { MCP_RECURRING_REPORTS } from './recurringReportDefinitions'
import { RecurringReportDetails } from './RecurringReportDetails'
import { SavedNotificationRow } from './SavedNotificationRow'

const meta: Meta = {
    title: 'Scenes-App/MCP Analytics/Notification Types Table',
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj

const noop = (): void => {}

function savedRow(name: string, summary: string, enabled: boolean): JSX.Element {
    return (
        <SavedNotificationRow
            key={name}
            name={name}
            to="#"
            summary={summary}
            enabled={enabled}
            onToggle={noop}
            toggleLoading={false}
            onDelete={noop}
            deleteDataAttr="story-delete"
        />
    )
}

const alertRow: NotificationTypeRow = {
    key: 'alert-tool-error',
    icon: <IconWarning />,
    headline: 'A tool call failed',
    lead: 'Which tool broke, what the agent wanted, and a link to the detail.',
    cadence: 'instant',
    saved: { total: 2, enabled: 1, truncated: false },
    action: (
        <LemonButton type="secondary" size="small" icon={<IconPlus />}>
            Add
        </LemonButton>
    ),
    preview: (
        <NotificationSlackPreview
            message="*query-events* failed on your MCP server *acme-mcp* (client: Claude Code). Agent intent: _find out why signups dropped after Tuesday's release_"
            buttonLabel="View tool detail"
            caption="Example"
        />
    ),
    savedRows: [
        savedRow('Failing tool calls to #mcp-alerts', 'Slack · #mcp-alerts', true),
        savedRow('Failing tool calls to on-call email', 'Email · oncall@example.com', false),
    ],
}

const reportRows: NotificationTypeRow[] = MCP_RECURRING_REPORTS.map((report) => ({
    key: `report-${report.key}`,
    icon: <IconCalendar />,
    headline: report.headline,
    lead: report.lead,
    tag: (
        <LemonTag type="completion" size="small">
            Beta
        </LemonTag>
    ),
    cadence: report.frequency,
    saved: { total: 0, enabled: 0, truncated: false },
    action: (
        <LemonButton type="primary" size="small">
            Set up
        </LemonButton>
    ),
    preview: <RecurringReportDetails covers={report.covers} prompt={report.prompt} />,
    savedRows: [],
}))

export const MixedStates: Story = {
    render: () => <NotificationTypesTable rows={[alertRow, ...reportRows]} />,
}

export const NothingSetUp: Story = {
    render: () => (
        <NotificationTypesTable
            rows={[
                {
                    ...alertRow,
                    saved: { total: 0, enabled: 0, truncated: false },
                    savedRows: [],
                    action: (
                        <LemonButton type="primary" size="small">
                            Set up
                        </LemonButton>
                    ),
                },
                ...reportRows,
            ]}
        />
    ),
}

export const Loading: Story = {
    // The skeletons are the point of this story, so the runner must not wait for them to go away.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    render: () => (
        <NotificationTypesTable
            rows={[alertRow, ...reportRows].map((row) => ({ ...row, saved: undefined, savedRows: [] }))}
        />
    ),
}

export const NarrowScene: Story = {
    render: () => (
        // An inline-size container needs a width of its own, or the story root collapses to nothing.
        <div className="@container w-lg max-w-full">
            <NotificationTypesTable rows={[alertRow, ...reportRows]} />
        </div>
    ),
}
