import { Meta, StoryObj } from '@storybook/react'

import { FeatureFlagCodeCleanupPanel } from './FeatureFlagCodeCleanupPanel'
import type { FeatureFlagCodeCleanupApi, FeatureFlagCodeCleanupRunApi } from './generated/api.schemas'

const available: FeatureFlagCodeCleanupApi = {
    unavailable_reason: null,
    suggested_outcome: 'enabled',
    outcome_options: ['enabled', 'disabled'],
    can_request: true,
    run: null,
}

const run = (overrides: Partial<FeatureFlagCodeCleanupRunApi>): FeatureFlagCodeCleanupRunApi => ({
    task_id: '0190f3c2-7a1b-7c3d-9e4f-5a6b7c8d9e0f',
    run_status: 'in_progress',
    is_terminal: false,
    pr_url: null,
    error_message: null,
    can_view_task: true,
    ...overrides,
})

const meta: Meta<typeof FeatureFlagCodeCleanupPanel> = {
    title: 'Scenes-App/Feature Flags/Code Cleanup Panel',
    component: FeatureFlagCodeCleanupPanel,
    args: {
        cleanup: available,
        repository: 'example-org/storefront',
        selectedOutcome: 'enabled',
        opening: false,
        error: null,
        statusStale: false,
        checkingStatus: false,
        onSelectOutcome: () => {},
        onOpen: () => {},
        onCheckStatus: () => {},
    },
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <div className="max-w-4xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof FeatureFlagCodeCleanupPanel>

export const Available: Story = {}

export const ChooseOutcome: Story = {
    args: {
        cleanup: {
            ...available,
            suggested_outcome: null,
            outcome_options: ['disabled', 'control', 'compact-layout'],
        },
        selectedOutcome: null,
    },
}

export const Opening: Story = {
    args: { cleanup: { ...available, can_request: false, run: run({}) } },
}

export const StatusStale: Story = {
    args: { cleanup: { ...available, can_request: false, run: run({}) }, statusStale: true },
}

export const Opened: Story = {
    args: {
        cleanup: {
            ...available,
            run: run({
                run_status: 'completed',
                is_terminal: true,
                pr_url: 'https://github.com/example-org/storefront/pull/482',
            }),
        },
    },
}

export const Failed: Story = {
    args: {
        cleanup: {
            ...available,
            run: run({
                run_status: 'failed',
                is_terminal: true,
                error_message: 'The sandbox ran out of time before the pull request was opened.',
            }),
        },
    },
}

export const FailedAfterOpeningPr: Story = {
    args: {
        cleanup: {
            ...available,
            run: run({
                run_status: 'failed',
                is_terminal: true,
                pr_url: 'https://github.com/example-org/storefront/pull/482',
            }),
        },
    },
}
