import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    buildLogsAlertFilterConfig,
    buildLogsAlertHogFunctionPayload,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
    PendingLogsAlertNotification,
} from '../logsAlertUtils'

describe('logsAlertUtils', () => {
    describe('buildLogsAlertFilterConfig', () => {
        it('includes alert_id property filter with exact operator', () => {
            const config = buildLogsAlertFilterConfig('alert-123')

            expect(config.properties).toEqual([
                {
                    key: 'alert_id',
                    value: 'alert-123',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ])
        })

        it('includes $logs_alert_firing event filter', () => {
            const config = buildLogsAlertFilterConfig('alert-123')

            expect(config.events).toEqual([
                {
                    id: '$logs_alert_firing',
                    type: 'events',
                },
            ])
        })
    })

    describe('buildLogsAlertHogFunctionPayload', () => {
        it('builds slack notification payload with channel and workspace', () => {
            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 42,
                slackChannelId: 'C123',
                slackChannelName: 'alerts',
            }

            const payload = buildLogsAlertHogFunctionPayload('alert-1', 'API errors', notification)

            expect(payload).toMatchObject({
                type: 'internal_destination',
                enabled: true,
                masking: null,
                name: 'API errors: Slack #alerts',
                template_id: 'template-slack',
            })
            expect(payload.inputs?.slack_workspace).toEqual({ value: 42 })
            expect(payload.inputs?.channel).toEqual({ value: 'C123' })
            expect(payload.filters?.events?.[0].id).toBe('$logs_alert_firing')
            expect(payload.filters?.properties?.[0].value).toBe('alert-1')
        })

        it('uses fallback name when alertName is undefined for slack', () => {
            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 1,
                slackChannelId: 'C456',
                slackChannelName: 'general',
            }

            const payload = buildLogsAlertHogFunctionPayload('alert-2', undefined, notification)

            expect(payload.name).toBe('Alert: Slack #general')
        })

        it('uses fallback channel name when slackChannelName is undefined', () => {
            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 1,
                slackChannelId: 'C789',
            }

            const payload = buildLogsAlertHogFunctionPayload('alert-3', 'My Alert', notification)

            expect(payload.name).toBe('My Alert: Slack #channel')
        })

        it('builds webhook notification payload with URL', () => {
            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
                webhookUrl: 'https://example.com/hook',
            }

            const payload = buildLogsAlertHogFunctionPayload('alert-4', 'DB errors', notification)

            expect(payload).toMatchObject({
                type: 'internal_destination',
                enabled: true,
                masking: null,
                name: 'DB errors: Webhook https://example.com/hook',
                template_id: 'template-webhook',
            })
            expect(payload.inputs?.url).toEqual({ value: 'https://example.com/hook' })
            expect(payload.inputs?.body?.value).toMatchObject({
                alert_name: '{event.properties.alert_name}',
                threshold_count: '{event.properties.threshold_count}',
                window_minutes: '{event.properties.window_minutes}',
                logs_url: '{project.url}/logs?{event.properties.logs_url_params}',
            })
        })

        it('uses fallback name when alertName is undefined for webhook', () => {
            const notification: PendingLogsAlertNotification = {
                type: LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
                webhookUrl: 'https://example.com/hook',
            }

            const payload = buildLogsAlertHogFunctionPayload('alert-5', undefined, notification)

            expect(payload.name).toBe('Alert: Webhook https://example.com/hook')
        })
    })
})
