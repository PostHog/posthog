import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { SelfDrivingSection } from './SelfDrivingSection'

// The "PR generation" card from the agents setup rail. It reads the team-wide config
// (`signals/config`) and the current user's personal override (`users/@me/signal_autonomy`), so both
// GETs are mocked per story to place the card in a given state.

interface CardState {
    /** `autostart_enabled` on the team config – the master switch. */
    enabled?: boolean
    /** Team-wide default threshold, always a concrete priority. */
    projectThreshold?: string
    /** Personal override, or null to inherit the project threshold ("Default"). */
    myThreshold?: string | null
    dailyLimit?: number | null
    reportsToday?: number
    /** Personal opt-in to being added as a GitHub assignee on the implementation PR. */
    githubAssign?: boolean
}

function Card({
    enabled = true,
    projectThreshold = 'P2',
    myThreshold = null,
    dailyLimit = null,
    reportsToday = 0,
    githubAssign = false,
}: CardState): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': {
                id: 'cfg-1',
                autostart_enabled: enabled,
                default_autostart_priority: projectThreshold,
                autostart_base_branches: {},
                max_reports_per_day: dailyLimit,
                reports_generated_today: reportsToday,
                daily_report_limit_reached: dailyLimit != null && reportsToday >= dailyLimit,
            },
            '/api/users/@me/signal_autonomy/': {
                id: 'auto-1',
                autostart_priority: myThreshold,
                slack_notification_channel: null,
                slack_notification_min_priority: null,
                github_assign_on_pull_request: githubAssign,
            },
            '/api/environments/:team_id/integrations/': { results: [] },
        },
    })
    // Mimic the agents rail (`w-80` aside + the column's `px-4 py-3`) so the card lays out as in the scene.
    return (
        <div className="w-80 px-4 py-3 bg-surface-secondary">
            <SelfDrivingSection />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/SelfDrivingSection',
    component: SelfDrivingSection,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
}
export default meta

type Story = StoryObj

export const NoDailyLimit: Story = {
    render: () => <Card />,
}

export const DailyLimitSet: Story = {
    render: () => <Card dailyLimit={10} reportsToday={3} />,
}

export const DailyLimitReached: Story = {
    render: () => <Card dailyLimit={10} reportsToday={10} />,
}

// Personal override set below the project default: "My threshold" reads P1+ while the project stays P2+.
export const PersonalOverride: Story = {
    render: () => <Card myThreshold="P1" />,
}

// No personal override: "My threshold" shows "Default" and inherits the project threshold.
export const PersonalDefault: Story = {
    render: () => <Card myThreshold={null} />,
}

// Personal GitHub assignment opted in: the row's switch reads on.
export const GitHubAssignmentOn: Story = {
    render: () => <Card githubAssign />,
}

// Master switch off: both thresholds are hidden and only the reassurance copy shows.
export const Disabled: Story = {
    render: () => <Card enabled={false} />,
}
