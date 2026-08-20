import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { SelfDrivingSection } from './SelfDrivingSection'

interface SectionState {
    dailyLimit: number | null
    reportsToday: number
}

function StateMocks({ state }: { state: SectionState }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': {
                id: 'cfg-1',
                autostart_enabled: true,
                default_autostart_priority: 'P4',
                autostart_base_branches: {},
                max_reports_per_day: state.dailyLimit,
                reports_generated_today: state.reportsToday,
                daily_report_limit_reached: state.dailyLimit != null && state.reportsToday >= state.dailyLimit,
            },
            '/api/environments/:team_id/integrations/': { results: [] },
        },
    })
    // Mimic the agents rail's narrow column so the card lays out as it does in the scene.
    return (
        <div className="w-[260px] p-4 bg-surface-secondary">
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
    },
}
export default meta

type Story = StoryObj

export const NoDailyLimit: Story = {
    render: () => <StateMocks state={{ dailyLimit: null, reportsToday: 0 }} />,
}

export const DailyLimitSet: Story = {
    render: () => <StateMocks state={{ dailyLimit: 10, reportsToday: 3 }} />,
}

export const DailyLimitReached: Story = {
    render: () => <StateMocks state={{ dailyLimit: 10, reportsToday: 10 }} />,
}
