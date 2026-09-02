import { isDataWarehouseViewTriggerConfig } from './data_warehouse_view'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('materialized view trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'data-warehouse-view')
        if (!triggerType) {
            throw new Error('Materialized view trigger type not registered')
        }
        return triggerType
    }

    describe('isDataWarehouseViewTriggerConfig', () => {
        it.each([
            {
                name: 'data-warehouse-view config',
                config: { type: 'data-warehouse-view', table_name: 'daily_revenue' } as any,
                expected: true,
            },
            {
                name: 'data-warehouse-table config',
                config: { type: 'data-warehouse-table', table_name: 'daily_revenue' } as any,
                expected: false,
            },
            { name: 'event config', config: { type: 'event', filters: {} } as any, expected: false },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(isDataWarehouseViewTriggerConfig(config)).toBe(expected)
        })
    })

    describe('validate', () => {
        it.each([
            {
                name: 'missing view name',
                config: { type: 'data-warehouse-view', table_name: '', filters: { properties: [] } },
                expected: { valid: false, errors: { table_name: 'Please select a materialized view' } },
            },
            {
                name: 'view name set',
                config: { type: 'data-warehouse-view', table_name: 'daily_revenue', filters: { properties: [] } },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'non data-warehouse-view config returns null',
                config: { type: 'data-warehouse-table', table_name: 'postgres.table_1' },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(getTriggerType().validate!(config as any)).toEqual(expected)
        })
    })

    it('is gated behind its own feature flag, separately from the source table trigger', () => {
        expect(getTriggerType().featureFlag).toBe('cdp-dwh-view-source')
    })

    it('buildConfig produces a config recognized by matchConfig', () => {
        const triggerType = getTriggerType()
        const config = triggerType.buildConfig()
        expect(config.type).toBe('data-warehouse-view')
        expect(triggerType.matchConfig!(config)).toBe(true)
    })
})
