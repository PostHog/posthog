import { useValues } from 'kea'

import { IconTelescope } from '@posthog/icons'

import { slackChannelName } from 'lib/integrations/slackChannel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { scoutDisplayName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { describeDashboardScoutSchedule } from './dashboardScout'
import { DashboardScoutRow, dashboardScoutsListLogic } from './dashboardScoutsListLogic'

function slackTarget({ scout }: DashboardScoutRow): string {
    const slack = scout.output_destinations?.slack
    if (slack?.users?.length) {
        return pluralize(slack.users.length, 'person', 'people')
    }
    const channel = slack?.channel ? slackChannelName(slack.channel) : undefined
    return channel ? `#${channel}` : '—'
}

const COLUMNS: LemonTableColumns<DashboardScoutRow> = [
    {
        title: 'Name',
        key: 'name',
        render: (_, row) => (
            <Link
                to={urls.inboxScout(row.scout.skill_name)}
                className="font-medium flex items-center gap-2"
                data-attr="dashboard-scout-name-link"
            >
                <IconTelescope />
                <span className="truncate">{scoutDisplayName(row.scout)}</span>
            </Link>
        ),
    },
    {
        title: 'Type',
        key: 'type',
        width: '7rem',
        render: () => <LemonTag>Scout</LemonTag>,
    },
    {
        title: 'Resource',
        key: 'resource',
        render: (_, row) => <Link to={urls.dashboard(row.dashboardId)}>Dashboard</Link>,
    },
    {
        title: 'Destination',
        key: 'destination',
        render: (_, row) => slackTarget(row),
    },
    {
        title: 'Recurrence',
        key: 'recurrence',
        render: (_, row) => describeDashboardScoutSchedule(row.scout.run_cron_schedule, row.scout.run_interval_minutes),
    },
    {
        title: 'Enabled',
        key: 'enabled',
        align: 'right',
        render: (_, row) =>
            row.scout.enabled ? <LemonTag type="success">On</LemonTag> : <LemonTag type="muted">Paused</LemonTag>,
    },
]

/** The project's dashboard scouts, listed above the subscriptions they sit alongside. Renders nothing when there are none. */
export function DashboardScoutsTable(): JSX.Element | null {
    const { dashboardScoutRows } = useValues(dashboardScoutsListLogic)

    if (dashboardScoutRows.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="mb-0">Dashboard scouts</h3>
                <p className="text-secondary text-sm mb-0">
                    Scouts that watch a dashboard and post in Slack. Open one to see its runs, notes and settings.
                </p>
            </div>
            <LemonTable
                dataSource={dashboardScoutRows}
                columns={COLUMNS}
                rowKey={(row) => row.scout.id}
                data-attr="dashboard-scouts-table"
            />
        </div>
    )
}
