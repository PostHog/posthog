import { LOGS_ALERT_FIRING_EVENT_ID, LOGS_ALERT_RESOLVED_EVENT_ID } from 'lib/constants'

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

        it('includes both firing and resolved event filters', () => {
            const config = buildLogsAlertFilterConfig('alert-123')

            expect(config.events).toEqual([
                {
                    id: LOGS_ALERT_FIRING_EVENT_ID,
                    type: 'events',
                },
                {
                    id: LOGS_ALERT_RESOLVED_EVENT_ID,
                    type: 'events',
                },
            ])
        })
    })

    describe('buildLogsAlertHogFunctionPayload', () => {
        it('builds slack payload with conditional blocks and both-event filter', () => {
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
            expect(payload.filters?.events).toHaveLength(2)
            expect(payload.filters?.events?.[0].id).toBe(LOGS_ALERT_FIRING_EVENT_ID)
            expect(payload.filters?.events?.[1].id).toBe(LOGS_ALERT_RESOLVED_EVENT_ID)

            // Slack blocks use if() conditionals for firing vs resolved copy
            const headerText = payload.inputs?.blocks?.value?.[0]?.text?.text
            expect(headerText).toContain("if(event.event == '$logs_alert_resolved'")
            expect(headerText).toContain('has resolved')
            expect(headerText).toContain('is firing')
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

        it('builds webhook payload with conditional event discriminator', () => {
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
                event: "{if(event.event == '$logs_alert_resolved', 'resolved', 'firing')}",
                alert_name: '{event.properties.alert_name}',
                result_count: '{event.properties.result_count}',
                threshold_count: '{event.properties.threshold_count}',
                threshold_operator: '{event.properties.threshold_operator}',
                window_minutes: '{event.properties.window_minutes}',
                logs_url: '{project.url}/logs?{event.properties.logs_url_params}',
            })
            expect(payload.filters?.events).toHaveLength(2)
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
