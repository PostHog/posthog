import { FilterLogicalOperator } from '~/types'

import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

import {
    buildRetentionConfigPayload,
    buildRetentionFormDefaults,
    LogsRetentionFormType,
} from './logsRetentionFormLogic'

const form = (overrides: Partial<LogsRetentionFormType> = {}): LogsRetentionFormType => ({
    name: 'keep api logs',
    enabled: true,
    retention_days: 30,
    filter_group: {
        type: FilterLogicalOperator.And,
        values: [{ key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: 'api' } as never],
    },
    ...overrides,
})

describe('logsRetentionFormLogic', () => {
    it('serializes retention_days and wraps the filter group in the stored envelope', () => {
        const config = buildRetentionConfigPayload(form())
        expect(config.retention_days).toEqual(30)
        // The ingestion worker unwraps a single-element AND envelope; the API stores it wrapped.
        expect(config.filter_group).toEqual({
            type: FilterLogicalOperator.And,
            values: [form().filter_group],
        })
    })

    it('round-trips a stored rule back into the form (unwraps the envelope, keeps the tier)', () => {
        const rule = {
            name: 'keep api logs',
            enabled: true,
            config: buildRetentionConfigPayload(form()),
        } as unknown as LogsRetentionRuleApi

        const defaults = buildRetentionFormDefaults(rule)
        expect(defaults.retention_days).toEqual(30)
        expect(defaults.filter_group).toEqual(form().filter_group)
    })

    it('falls back to the default tier when a stored rule has a non-tier retention value', () => {
        const rule = {
            name: 'legacy',
            enabled: false,
            config: { retention_days: 45, filter_group: { type: 'AND', values: [] } },
        } as unknown as LogsRetentionRuleApi

        expect(buildRetentionFormDefaults(rule).retention_days).toEqual(14)
    })
})
