import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    PlatformAlertConfigurationApi,
    PlatformAlertDestinationApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { userEvent } from 'storybook/test'

import { TracesAlertsTab } from './TracesAlertsTab'

const BASE: PlatformAlertConfigurationApi = {
    id: '0192a5b0-0000-7000-8000-000000000501',
    name: 'Checkout error rate',
    enabled: true,
    labels: {},
    annotations: {},
    source_kind: 'traces',
    source_config: {
        filters: { serviceNames: ['checkout'], filterGroup: null },
        condition: {
            measure: 'error_rate',
            percentile: null,
            threshold: 0.05,
            threshold_operator: 'above',
            window_minutes: 5,
        },
    },
    check_interval_minutes: 1,
    recurrence_unit: null,
    anchor_time: null,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    schedule_restriction: null,
    next_check_at: '2026-11-11T12:01:00Z',
    consecutive_failures: 0,
    legacy_configuration_id: null,
    grouping: { mode: 'single', keys: [], max_instances: 100, on_overflow: 'degrade_visible' },
    snooze_until: null,
    check_status: 'ok',
    overflowed_groups: 0,
    overflow_is_lower_bound: false,
    owner: 'platform',
    created_at: '2026-11-01T09:00:00Z',
    updated_at: '2026-11-10T09:00:00Z',
    alerts: [
        {
            id: '0192a5b0-0000-7000-8000-000000000601',
            grouping_key: '',
            state: 'firing',
            firing_started_at: '2026-11-11T11:42:00Z',
            last_notified_at: '2026-11-11T11:42:05Z',
            snooze_until: null,
            labels: {},
        },
    ],
}

const ALERTS: PlatformAlertConfigurationApi[] = [
    BASE,
    {
        ...BASE,
        id: '0192a5b0-0000-7000-8000-000000000502',
        name: 'Slow API endpoints',
        source_config: {
            filters: { serviceNames: ['api-gateway', 'payments-api'], filterGroup: null },
            condition: {
                measure: 'latency',
                percentile: 95,
                threshold: 750,
                threshold_operator: 'above',
                window_minutes: 15,
            },
        },
        grouping: { mode: 'by_result_labels', keys: ['service_name', 'name'], max_instances: 100 },
        alerts: [],
    },
    {
        ...BASE,
        id: '0192a5b0-0000-7000-8000-000000000503',
        name: 'Ingest traffic stopped',
        enabled: false,
        source_config: {
            filters: { serviceNames: [], filterGroup: null },
            condition: {
                measure: 'request_count',
                percentile: null,
                threshold: 10,
                threshold_operator: 'below',
                window_minutes: 10,
            },
        },
        next_check_at: null,
        alerts: [],
    },
]

const DESTINATIONS: PlatformAlertDestinationApi[] = [
    {
        id: '0192a5b0-0000-7000-8000-000000000701',
        type: 'slack',
        enabled: true,
        event_kinds: ['firing', 'resolved', 'errored', 'broken'],
        slack_workspace_id: 1,
        slack_channel_id: 'C0000000001',
        slack_channel_name: 'checkout-alerts',
    },
    {
        id: '0192a5b0-0000-7000-8000-000000000702',
        type: 'webhook',
        enabled: true,
        event_kinds: ['firing', 'resolved', 'errored', 'broken'],
        webhook_url: 'https://hooks.example.com',
    },
]

const meta: Meta<typeof TracesAlertsTab> = {
    component: TracesAlertsTab,
    title: 'Products/Tracing/Alerts tab',
    parameters: {
        layout: 'padded',
        mockDate: '2026-11-11T12:00:00Z',
        // Rendered to catch errors, not snapshotted: the tab is used in one scene and has no visual contract yet.
        testOptions: { snapshotBrowsers: [] },
    },
    // The tab's edit controls need tracing editor access, and the default story context grants none.
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.Tracing]: AccessControlLevel.Editor,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/platform_alerts/': { count: ALERTS.length, results: ALERTS },
                '/api/projects/:team_id/platform_alerts/:id/destinations/': DESTINATIONS,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof TracesAlertsTab>

export const List: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/platform_alerts/': { count: 0, results: [] } },
        }),
    ],
}

export const CreateModal: Story = {
    play: async ({ canvasElement }) => {
        const button = await within(canvasElement).findByText('New alert')
        await userEvent.click(button)
    },
}

export const EditModal: Story = {
    play: async ({ canvasElement }) => {
        const name = await within(canvasElement).findByText('Checkout error rate')
        await userEvent.click(name)
    },
}
