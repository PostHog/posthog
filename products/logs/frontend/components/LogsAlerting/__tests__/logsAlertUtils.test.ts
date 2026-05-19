import { FilterLogicalOperator, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsAlertConfigurationApi, ThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertFormType } from '../logsAlertFormLogic'
import { buildLogsAlertFilterConfig, groupLogsAlertDestinations, runPreEnableChecks } from '../logsAlertUtils'

const baseAlert = (overrides: Partial<LogsAlertConfigurationApi> = {}): LogsAlertConfigurationApi =>
    ({
        id: 'a',
        destination_types: ['slack'],
        ...overrides,
    }) as LogsAlertConfigurationApi

const baseForm = (overrides: Partial<LogsAlertFormType> = {}): LogsAlertFormType => ({
    name: 'A',
    severityLevels: ['error'],
    serviceNames: [],
    filterGroup: { type: FilterLogicalOperator.And, values: [] },
    thresholdOperator: ThresholdOperatorEnumApi.Above,
    thresholdCount: 1,
    windowMinutes: 5,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    cooldownMinutes: 0,
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

    describe('groupLogsAlertDestinations', () => {
        const slackHf = (id: string, channel: string, enabled = true): HogFunctionType =>
            ({
                id,
                name: `slack-${id}`,
                enabled,
                inputs: { channel: { value: channel } },
                filters: {},
            }) as unknown as HogFunctionType

        const webhookHf = (id: string, url: string, enabled = true): HogFunctionType =>
            ({
                id,
                name: `webhook-${id}`,
                enabled,
                inputs: { url: { value: url } },
                filters: {},
            }) as unknown as HogFunctionType

        const resolveSlack = (channelValue: string): string | null => `channel-for-${channelValue}`

        it('collapses multiple HogFunctions for the same slack channel into one group', () => {
            const firing = slackHf('hf-1', 'C123')
            const resolved = slackHf('hf-2', 'C123')

            const groups = groupLogsAlertDestinations([firing, resolved], resolveSlack)

            expect(groups).toHaveLength(1)
            expect(groups[0]).toMatchObject({
                key: 'slack:C123',
                type: 'slack',
                label: 'Slack #channel-for-C123',
                enabled: true,
            })
            expect(groups[0].hogFunctions).toHaveLength(2)
        })

        it('collapses multiple HogFunctions for the same webhook url into one group', () => {
            const a = webhookHf('hf-1', 'https://example.com/hook')
            const b = webhookHf('hf-2', 'https://example.com/hook')

            const groups = groupLogsAlertDestinations([a, b], resolveSlack)

            expect(groups).toHaveLength(1)
            expect(groups[0]).toMatchObject({
                key: 'webhook:https://example.com/hook',
                type: 'webhook',
                label: 'Webhook https://example.com/hook',
            })
            expect(groups[0].hogFunctions).toHaveLength(2)
        })

        it('keeps distinct slack channels and webhook urls as separate groups', () => {
            const groups = groupLogsAlertDestinations(
                [
                    slackHf('a', 'C123'),
                    slackHf('b', 'C456'),
                    webhookHf('c', 'https://one.example'),
                    webhookHf('d', 'https://two.example'),
                ],
                resolveSlack
            )

            expect(groups.map((g) => g.key).sort()).toEqual([
                'slack:C123',
                'slack:C456',
                'webhook:https://one.example',
                'webhook:https://two.example',
            ])
        })

        it('marks a group as disabled when any HogFunction in it is disabled (AND semantics)', () => {
            const firing = slackHf('hf-1', 'C123', true)
            const resolved = slackHf('hf-2', 'C123', false)

            const groups = groupLogsAlertDestinations([firing, resolved], resolveSlack)

            expect(groups).toHaveLength(1)
            expect(groups[0].enabled).toBe(false)
        })

        it('falls back to a bare Slack label when the channel name cannot be resolved', () => {
            const hf = slackHf('hf-1', 'C_UNKNOWN')

            const groups = groupLogsAlertDestinations([hf], () => null)

            expect(groups[0].label).toBe('Slack')
        })

        it('produces an isolated per-HogFunction group for unrecognised inputs', () => {
            const unknown = {
                id: 'hf-x',
                name: 'Weird destination',
                enabled: true,
                inputs: {},
                filters: {},
            } as unknown as HogFunctionType

            const groups = groupLogsAlertDestinations([unknown], resolveSlack)

            expect(groups).toHaveLength(1)
            expect(groups[0].key).toBe('unknown:hf-x')
            expect(groups[0].label).toBe('Weird destination')
        })
    })

    describe('runPreEnableChecks', () => {
        it('returns ok when filters and destinations are present', () => {
            expect(runPreEnableChecks(baseAlert(), baseForm())).toEqual({ ok: true })
        })

        it('blocks when no filters', () => {
            const result = runPreEnableChecks(
                baseAlert(),
                baseForm({
                    severityLevels: [],
                    serviceNames: [],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                })
            )
            expect(result).toEqual({ blocked: true, reason: 'Add at least one filter to enable' })
        })

        it('warns when no destinations', () => {
            const result = runPreEnableChecks(baseAlert({ destination_types: [] }), baseForm())
            expect(result).toMatchObject({ warning: { title: 'No notifications configured' } })
        })

        it('blocks before warning when both apply', () => {
            const result = runPreEnableChecks(
                baseAlert({ destination_types: [] }),
                baseForm({
                    severityLevels: [],
                    serviceNames: [],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                })
            )
            expect(result).toEqual({ blocked: true, reason: 'Add at least one filter to enable' })
        })
    })
})
