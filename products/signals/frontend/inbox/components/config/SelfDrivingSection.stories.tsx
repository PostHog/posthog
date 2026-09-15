import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { SettingsSection } from '../tabs/SettingsSection'
import { SelfDrivingSection } from './SelfDrivingSection'

// The Autonomy settings. They read the team-wide config (`signals/config`) and the current user's
// personal override (`users/@me/signal_autonomy`), so both GETs are mocked per story to place the
// section in a given state.

interface CardState {
    /** `autostart_enabled` on the team config – the master switch. */
    enabled?: boolean
    /** Team-wide default threshold, always a concrete priority. */
    projectThreshold?: string
    /** Personal override, or null to inherit the project threshold ("Default"). */
    myThreshold?: string | null
    /** Repositories that branch from somewhere other than their default branch. */
    baseBranches?: Record<string, string>
    dailyLimit?: number | null
    reportsToday?: number
    /** Personal opt-in to being added as a GitHub assignee on the implementation PR. */
    githubAssign?: boolean
    /** Whether the project opens self-driving PRs ready for review instead of draft. */
    projectPrReady?: boolean
    /** Personal override for that, or null to follow the project ("Default"). */
    myPrReady?: boolean | null
    /** Connected integrations the issue tracker picker can choose from. */
    integrations?: Record<string, unknown>[]
    /** Integration id the project already tracks issues in, and where inside it they land. */
    issueTrackingIntegration?: number | null
    issueTrackingConfig?: Record<string, string>
}

const GITHUB_INTEGRATION = { id: 1, kind: 'github', display_name: 'PostHog', config: {}, created_at: '2024-03-01' }

function useAutonomyMocks({
    enabled = true,
    projectThreshold = 'P2',
    myThreshold = null,
    baseBranches = {},
    dailyLimit = null,
    reportsToday = 0,
    githubAssign = false,
    projectPrReady = false,
    myPrReady = null,
    integrations = [],
    issueTrackingIntegration = null,
    issueTrackingConfig = {},
}: CardState): void {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': {
                id: 'cfg-1',
                autostart_enabled: enabled,
                default_autostart_priority: projectThreshold,
                autostart_base_branches: baseBranches,
                issue_tracking_integration: issueTrackingIntegration,
                issue_tracking_config: issueTrackingConfig,
                max_reports_per_day: dailyLimit,
                reports_generated_today: reportsToday,
                daily_report_limit_reached: dailyLimit != null && reportsToday >= dailyLimit,
                default_open_pull_request_ready: projectPrReady,
            },
            '/api/users/@me/signal_autonomy/': {
                id: 'auto-1',
                autostart_priority: myThreshold,
                slack_notification_channel: null,
                slack_notification_min_priority: null,
                github_assign_on_pull_request: githubAssign,
                github_open_pull_request_ready: myPrReady,
            },
            '/api/projects/:team_id/integrations/': { results: integrations },
        },
    })
}

/** The legacy agents rail: a `w-80` aside with the column's `px-4 py-3`, so the card lays out as in the scene. */
function Card(state: CardState): JSX.Element {
    useAutonomyMocks(state)
    return (
        <div className="w-80 px-4 py-3 bg-surface-secondary">
            <SelfDrivingSection />
        </div>
    )
}

/** The Settings tab: the section inside its card, at the tab's `max-w-4xl` or pinned narrow. */
function SettingsCard({ width, ...state }: CardState & { width: 'wide' | 'narrow' }): JSX.Element {
    useAutonomyMocks(state)
    // 32rem is about what a 1280px window leaves the scene with the side panel open.
    return (
        <div className={width === 'wide' ? 'w-[56rem] px-6 py-6' : 'w-[32rem] px-6 py-6'}>
            <SettingsSection
                title="Autonomy"
                description="How much agents do on their own: opening pull requests, and how many reports arrive each day."
            >
                <SelfDrivingSection />
            </SettingsSection>
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

const REDESIGN = { featureFlags: [FEATURE_FLAGS.INBOX_REDESIGN] }

// The Settings tab at full width: controls sit right of their labels.
export const SettingsTab: Story = {
    parameters: REDESIGN,
    render: () => <SettingsCard width="wide" dailyLimit={10} reportsToday={3} />,
}

// The Settings tab in a narrow scene: wide controls wrap below their labels, nothing clips.
export const SettingsTabNarrow: Story = {
    parameters: REDESIGN,
    render: () => <SettingsCard width="narrow" dailyLimit={10} reportsToday={3} />,
}

// A repository that branches from `develop`: the override list and the picker render under Base branches.
export const SettingsTabBaseBranches: Story = {
    parameters: REDESIGN,
    render: () => (
        <SettingsCard
            width="wide"
            integrations={[GITHUB_INTEGRATION]}
            baseBranches={{ 'posthog/posthog.com': 'develop' }}
        />
    ),
}

// GitHub disconnected after an override was saved: the override stays readable and removable, the picker hides.
export const SettingsTabBaseBranchesWithoutGitHub: Story = {
    parameters: REDESIGN,
    render: () => <SettingsCard width="wide" baseBranches={{ 'posthog/posthog.com': 'develop' }} />,
}

// Master switch off in the Settings tab: the project threshold, base branches, and personal threshold hide.
export const SettingsTabDisabled: Story = {
    parameters: REDESIGN,
    render: () => <SettingsCard width="wide" enabled={false} />,
}

export const NoDailyLimit: Story = {
    render: () => <Card />,
}

export const DailyLimitSet: Story = {
    render: () => <Card dailyLimit={10} reportsToday={3} />,
}

export const DailyLimitReached: Story = {
    render: () => <Card dailyLimit={10} reportsToday={10} />,
}

// Personal override set below the project default: the personal threshold reads P1+ while the project stays P2+.
export const PersonalOverride: Story = {
    render: () => <Card myThreshold="P1" />,
}

// No personal override: the personal threshold shows "Default" and inherits the project threshold.
export const PersonalDefault: Story = {
    render: () => <Card myThreshold={null} />,
}

// Personal GitHub assignment opted in: the row's switch reads on.
export const GitHubAssignmentOn: Story = {
    render: () => <Card githubAssign />,
}

// A reviewer who opted into the full CI matrix inside a project that still defaults to draft.
export const PullRequestReadyForReview: Story = {
    render: () => <Card myPrReady />,
}

// Master switch off: both thresholds are hidden and only the reassurance copy shows.
export const Disabled: Story = {
    render: () => <Card enabled={false} />,
}

// No tracker connected: the issue tracker row offers to connect one.
export const IssueTrackerUnavailable: Story = {
    render: () => <Card />,
}

// A project under a change-management control: every PR gets a GitHub issue in `PostHog/posthog`.
export const IssueTrackerConfigured: Story = {
    render: () => (
        <Card
            integrations={[GITHUB_INTEGRATION]}
            issueTrackingIntegration={1}
            issueTrackingConfig={{ repository: 'posthog' }}
        />
    ),
}
