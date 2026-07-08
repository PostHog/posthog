import { FilterLogicalOperator } from '~/types'

import { LogsSamplingRuleApi, RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import {
    buildSamplingConfigPayload,
    buildSamplingFormDefaults,
    LogsSamplingFormType,
    rateLimitAmountToKbPerSecond,
} from './logsSamplingFormLogic'

const rateLimitForm = (overrides: Partial<LogsSamplingFormType> = {}): LogsSamplingFormType => ({
    name: 'cap smokescreen',
    enabled: true,
    rule_type: RuleTypeEnumApi.RateLimit,
    filter_group: { type: FilterLogicalOperator.And, values: [] },
    rate_limit_amount: '1',
    rate_limit_unit: 'MB/s',
    ...overrides,
})

describe('logsSamplingFormLogic serialization', () => {
    it('serializes a path_drop rule into filter_group-only config', () => {
        const innerGroup = {
            type: FilterLogicalOperator.And,
            values: [{ key: 'service.name', operator: 'exact', value: 'api', type: 'log_resource_attribute' }],
        } as LogsSamplingFormType['filter_group']

        const config = buildSamplingConfigPayload(
            rateLimitForm({ rule_type: RuleTypeEnumApi.PathDrop, filter_group: innerGroup })
        )

        // The whole config is the wrapped filter group — the worker evaluates
        // config.filter_group directly, and nothing else belongs in the payload.
        expect(config).toEqual({
            filter_group: { type: FilterLogicalOperator.And, values: [innerGroup] },
        })
    })

    it.each([
        ['1', 'MB/s', 1000],
        ['50', 'KB/s', 50],
        ['1.5', 'MB/s', 1500],
        ['2', 'GB/s', 2_000_000],
    ] as const)('converts %s %s into %s KB/s', (amount, unit, expected) => {
        expect(rateLimitAmountToKbPerSecond(amount, unit)).toEqual(expected)
    })

    it('serializes a rate-limit rule into byte-mode config the ingestion worker enforces on', () => {
        const config = buildSamplingConfigPayload(rateLimitForm({ rate_limit_amount: '1', rate_limit_unit: 'MB/s' }))

        // Byte mode: `kb_per_second` is what compile-rules.ts parses with costUnit 'bytes'.
        expect(config.kb_per_second).toEqual(1000)
        expect(config.burst_kb).toEqual(10000)
        // The records-per-second fields must NOT be written — that was the bug.
        expect(config).not.toHaveProperty('logs_per_second')
        expect(config).not.toHaveProperty('burst_logs')
    })

    it('lowering the limit changes the stored byte threshold (50 KB/s != 1 MB/s)', () => {
        const oneMb = buildSamplingConfigPayload(rateLimitForm({ rate_limit_amount: '1', rate_limit_unit: 'MB/s' }))
        const fiftyKb = buildSamplingConfigPayload(rateLimitForm({ rate_limit_amount: '50', rate_limit_unit: 'KB/s' }))

        expect(oneMb.kb_per_second).toEqual(1000)
        expect(fiftyKb.kb_per_second).toEqual(50)
        expect(oneMb.kb_per_second).not.toEqual(fiftyKb.kb_per_second)
    })

    it('round-trips a byte-mode rule back into the form', () => {
        const rule = {
            name: 'cap smokescreen',
            enabled: true,
            rule_type: RuleTypeEnumApi.RateLimit,
            config: { kb_per_second: 1000, burst_kb: 10000, filter_group: { type: 'AND', values: [] } },
        } as unknown as LogsSamplingRuleApi

        const form = buildSamplingFormDefaults(rule)
        expect(form.rate_limit_amount).toEqual('1')
        expect(form.rate_limit_unit).toEqual('MB/s')
    })

    it('still displays legacy rules saved with logs_per_second so they can be re-saved', () => {
        const legacy = {
            name: 'legacy cap',
            enabled: true,
            rule_type: RuleTypeEnumApi.RateLimit,
            config: { logs_per_second: 50, burst_logs: 500 },
        } as unknown as LogsSamplingRuleApi

        const form = buildSamplingFormDefaults(legacy)
        expect(form.rate_limit_amount).toEqual('50')
        expect(form.rate_limit_unit).toEqual('KB/s')

        // Re-saving rewrites it into byte mode.
        const config = buildSamplingConfigPayload(form)
        expect(config.kb_per_second).toEqual(50)
        expect(config).not.toHaveProperty('logs_per_second')
    })
})
