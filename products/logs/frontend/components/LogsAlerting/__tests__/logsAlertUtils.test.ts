import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, SlackChannelType } from '~/types'

import {
    LogsAlertDestinationConfigApi,
    LogsAlertThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertFormType } from '../logsAlertFormLogic'
import { buildLogsAlertFilterConfig, destinationLabel, runPreEnableChecks } from '../logsAlertUtils'

const baseForm = (overrides: Partial<LogsAlertFormType> = {}): LogsAlertFormType => ({
    name: 'A',
    severityLevels: ['error'],
    serviceNames: [],
    filterGroup: { type: FilterLogicalOperator.And, values: [] },
    thresholdOperator: LogsAlertThresholdOperatorEnumApi.Above,
    thresholdCount: 1,
    windowMinutes: 5,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    cooldownMinutes: 0,
    scheduleRestriction: null,
    ...overrides,
})

describe('logsAlertUtils', () => {
    describe('buildLogsAlertFilterConfig', () => {
        it('filters by alert_id property only so it matches every per-event HogFunction', () => {
            const config = buildLogsAlertFilterConfig('alert-123')

            expect(config.properties).toEqual([
                {
                    key: 'alert_id',
                    value: 'alert-123',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ])
            // Deliberately no events array — see comment on buildLogsAlertFilterConfig.
            expect(config.events).toBeUndefined()
        })
    })

    describe('destinationLabel', () => {
        const slackDestination = (workspaceId: number): LogsAlertDestinationConfigApi => ({
            hog_function_ids: ['hf-1'],
            type: 'slack',
            enabled: true,
            slack_workspace_id: workspaceId,
            slack_channel_id: 'C123',
        })

        const channels: SlackChannelType[] = [
            { id: 'C123', name: 'alerts', is_private: false, is_ext_shared: false, is_member: true },
        ]

        it('names a Slack destination after its channel', () => {
            expect(destinationLabel(slackDestination(1), { workspaceId: 1, channels })).toBe('Slack #alerts')
        })

        // The server groups Slack destinations by workspace and channel. Labelling from the
        // wrong workspace's channel list would show one destination under another's name.
        it('does not borrow a channel name from another Slack workspace', () => {
            expect(destinationLabel(slackDestination(2), { workspaceId: 1, channels })).toBe('Slack')
        })

        it('falls back to a bare Slack label when the channel is not in the list', () => {
            expect(destinationLabel(slackDestination(1), { workspaceId: 1, channels: [] })).toBe('Slack')
        })

        it('names webhook and Teams destinations after their url', () => {
            const slack = { workspaceId: 1, channels }

            expect(
                destinationLabel(
                    {
                        hog_function_ids: ['hf-1'],
                        type: 'webhook',
                        enabled: true,
                        webhook_url: 'https://example.com/…',
                    },
                    slack
                )
            ).toBe('Webhook https://example.com/…')
            expect(
                destinationLabel(
                    {
                        hog_function_ids: ['hf-2'],
                        type: 'teams',
                        enabled: true,
                        webhook_url: 'https://teams.example/…',
                    },
                    slack
                )
            ).toBe('Microsoft Teams https://teams.example/…')
        })
    })

    describe('runPreEnableChecks', () => {
        it('returns ok when filters are present', () => {
            expect(runPreEnableChecks(baseForm())).toEqual({ ok: true })
        })

        it('blocks when no filters', () => {
            const result = runPreEnableChecks(
                baseForm({
                    severityLevels: [],
                    serviceNames: [],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                })
            )
            expect(result).toEqual({ blocked: true, reason: 'Add at least one filter to enable' })
        })

        it('allows an alert without notification destinations', () => {
            expect(runPreEnableChecks(baseForm())).toEqual({ ok: true })
        })
    })
})
