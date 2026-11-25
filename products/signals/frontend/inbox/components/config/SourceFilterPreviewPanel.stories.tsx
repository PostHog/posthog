import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import type {
    SourceFilterPreviewRecordApi,
    SourceFilterPreviewResponseApi,
} from 'products/signals/frontend/generated/api.schemas'

import { expect, userEvent } from 'storybook/test'

import { SourceFilterPreviewPanel } from './SourceFilterPreviewPanel'

const NOW = '2026-11-19T15:00:00Z'

function issue(number: number, title: string, hoursAgo: number, malformed = false): SourceFilterPreviewRecordApi {
    return {
        id: `issue-${number}`,
        identifier: `ENG-${number}`,
        title,
        url: `https://linear.app/example/issue/ENG-${number}`,
        created_at: new Date(Date.parse(NOW) - hoursAgo * 3_600_000).toISOString(),
        malformed,
        field_values: {},
    }
}

const PASSING = [
    issue(2481, 'Checkout button unresponsive on Safari 18', 2),
    issue(2479, 'Export to CSV drops rows past 10k', 5),
    issue(2477, 'Push notifications arrive twice on Android', 11),
    issue(2476, 'Customer asks for SSO with Okta groups', 14),
    issue(2473, 'Dark mode contrast too low on settings page', 31),
    issue(2472, 'Webhook retries ignore Retry-After header', 40),
    issue(2470, 'Search results ignore accented characters', 55),
    issue(2469, 'Crash when opening a shared link offline', 63),
    issue(2467, 'Add audit log entry for API key rotation', 82),
    issue(2465, 'Timezone picker shows UTC offsets twice', 101),
]

const EXCLUDED = [
    issue(2480, 'Bump eslint plugin to latest', 3),
    issue(2478, 'Investigate flaky billing test', 8),
    issue(2475, 'Onboarding checklist step 3 never completes', 20),
    issue(2474, 'Q4 planning doc review', 26),
    issue(2471, 'Rotate staging database credentials', 46),
    issue(2468, 'Refund request for duplicate invoice', 70),
    issue(2466, 'Imported issue with a label payload that could not be parsed', 90, true),
    issue(2464, 'Team offsite logistics', 120),
    issue(2462, 'iOS widget shows stale numbers', 150),
]

function response(overrides: Partial<SourceFilterPreviewResponseApi>): SourceFilterPreviewResponseApi {
    return {
        status: 'ok',
        error: null,
        error_code: null,
        error_start: null,
        error_end: null,
        catalog_version: 2,
        lookback_days: 7,
        total_count: 0,
        passing_count: 0,
        excluded_count: 0,
        malformed_count: 0,
        passing: [],
        excluded: [],
        ...overrides,
    }
}

const MIXED = response({
    total_count: 184,
    passing_count: 101,
    excluded_count: 83,
    malformed_count: 9,
    passing: PASSING,
    excluded: EXCLUDED,
})

const meta: Meta<typeof SourceFilterPreviewPanel> = {
    title: 'Scenes-App/Inbox/SourceFilterPreviewPanel',
    component: SourceFilterPreviewPanel,
    args: {
        result: MIXED,
        loading: false,
        requestError: null,
        onRetry: () => {},
        sourceLabel: 'Linear',
        noun: 'issue',
    },
    render: (args) => (
        // About the width of the preview column beside the editor in the filter modal.
        <div className="w-[34rem]">
            <SourceFilterPreviewPanel {...args} />
        </div>
    ),
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: NOW,
        featureFlags: [FEATURE_FLAGS.SIGNALS_SOURCE_FILTERS],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof SourceFilterPreviewPanel>

export const MixedResults: Story = {}

export const NothingPasses: Story = {
    args: {
        result: response({
            total_count: 184,
            excluded_count: 184,
            excluded: EXCLUDED.filter((record) => !record.malformed),
        }),
    },
    play: async ({ canvas }) => {
        await userEvent.click(await canvas.findByRole('button', { name: /Passes/ }))
        await expect(await canvas.findByText(/no new reports would come from Linear/)).toBeVisible()
    },
}

export const NoIssuesInWindow: Story = {
    args: { result: response({}) },
}

export const UpdatingOverAnOldResult: Story = {
    args: { loading: true },
}

export const InitialLoading: Story = {
    args: { result: null, loading: true },
}

export const InvalidExpression: Story = {
    args: {
        result: response({
            status: 'invalid_expression',
            error: 'Unknown field "priorty". Use one of the listed fields.',
            error_code: 'unknown_field',
            error_start: 37,
            error_end: 44,
        }),
    },
}

export const NotConnected: Story = {
    args: { result: response({ status: 'not_connected' }) },
}

export const NotSynced: Story = {
    args: { result: response({ status: 'not_synced' }) },
}

export const AccessDenied: Story = {
    args: { result: response({ status: 'access_denied' }) },
}

export const IncompatibleTable: Story = {
    args: { result: response({ status: 'incompatible_table' }) },
}

export const QueryFailed: Story = {
    args: { result: response({ status: 'query_failed', error: 'The preview query did not run.' }) },
}

export const Throttled: Story = {
    args: { requestError: 'throttled' },
}

export const RequestFailed: Story = {
    args: { result: null, requestError: 'failed' },
}

export const PhoneWidth: Story = {
    render: (args) => (
        // A 390px phone screen less the side padding of the modal.
        <div className="w-[360px]">
            <SourceFilterPreviewPanel {...args} />
        </div>
    ),
}
