import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { MetricsAlertingSection } from './MetricsAlertingSection'

const FIRING_ALERT: PlatformAlertConfigurationApi = {
    id: '0192a5b0-0000-7000-8000-000000000001',
    name: 'Checkout error rate above 5 per second',
    enabled: true,
    labels: { team: 'checkout', severity: 'critical' },
    annotations: {},
    created_by: null,
    last_checked_at: null,
    last_error_message: null,
    state_timeline: [],
    destination_types: [],
    source_kind: 'metrics',
    source_config: {
        query: 'sum by (service_name) (rate(http_requests_errors_total{service_name="checkout"}[5m]))',
        condition: { kind: 'threshold', operator: 'gt', threshold: 5 },
    },
    check_interval_minutes: 1,
    recurrence_unit: null,
    anchor_time: null,
    evaluation_periods: 3,
    datapoints_to_alarm: 2,
    cooldown_minutes: 0,
    schedule_restriction: null,
    next_check_at: '2026-10-05T12:01:00Z',
    consecutive_failures: 0,
    legacy_configuration_id: null,
    grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 100, on_overflow: 'degrade_visible' },
    snooze_until: null,
    check_status: 'ok',
    overflowed_groups: 0,
    overflow_is_lower_bound: false,
    owner: 'platform',
    created_at: '2026-09-20T09:00:00Z',
    updated_at: '2026-10-01T09:00:00Z',
    alerts: [
        {
            id: '0192a5b0-0000-7000-8000-000000000101',
            grouping_key: '{"service_name":"checkout"}',
            state: 'firing',
            firing_started_at: '2026-10-05T11:42:00Z',
            last_notified_at: '2026-10-05T11:42:05Z',
            snooze_until: null,
            labels: { service_name: 'checkout' },
        },
    ],
}

const DISABLED_ALERT: PlatformAlertConfigurationApi = {
    ...FIRING_ALERT,
    id: '0192a5b0-0000-7000-8000-000000000002',
    name: 'Ingestion lag series present',
    enabled: false,
    labels: {},
    source_config: {
        query: 'max by (partition) (kafka_consumergroup_lag) > 100000',
        condition: { kind: 'present' },
    },
    next_check_at: null,
    grouping: { mode: 'single', keys: [], max_instances: 100, on_overflow: 'degrade_visible' },
    alerts: [],
}

const meta: Meta<typeof MetricsAlertingSection> = {
    component: MetricsAlertingSection,
    title: 'Scenes-App/Metrics/Alerting',
    parameters: {
        mockDate: '2026-10-05T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.PLATFORM_ALERTS_SOURCE_METRICS],
        testOptions: { waitForSelector: '[data-attr="metrics-alert-row-name"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/platform_alerts/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [FIRING_ALERT, DISABLED_ALERT],
                },
                [`/api/projects/:team_id/platform_alerts/${FIRING_ALERT.id}/destinations/`]: [
                    {
                        id: '0192a5b0-0000-7000-8000-000000000201',
                        type: 'webhook',
                        enabled: true,
                        event_kinds: ['firing', 'resolved', 'errored', 'broken'],
                        webhook_url: 'https://hooks.example.com',
                    },
                ],
                '/api/environments/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof MetricsAlertingSection>

export const AlertList: Story = {}

// The width a scene gets with the nav sidebar and the side panel open on a laptop.
export const AlertListNarrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
