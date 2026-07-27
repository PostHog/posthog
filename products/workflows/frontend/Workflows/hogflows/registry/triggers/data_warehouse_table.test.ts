import { isDataWarehouseTableTriggerConfig } from './data_warehouse_table'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('data warehouse table trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'data-warehouse-table')
        if (!triggerType) {
            throw new Error('Data warehouse table trigger type not registered')
        }
        return triggerType
    }

    describe('isDataWarehouseTableTriggerConfig', () => {
        it.each([
            {
                name: 'data-warehouse-table config',
                config: { type: 'data-warehouse-table', table_name: 'x' } as any,
                expected: true,
            },
            { name: 'event config', config: { type: 'event', filters: {} } as any, expected: false },
            { name: 'schedule config', config: { type: 'schedule' } as any, expected: false },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(isDataWarehouseTableTriggerConfig(config)).toBe(expected)
        })
    })

    describe('validate', () => {
        it.each([
            {
                name: 'missing table name',
                config: { type: 'data-warehouse-table', table_name: '', filters: { properties: [] } },
                expected: { valid: false, errors: { table_name: 'Please select a data warehouse table' } },
            },
            {
                name: 'table name set',
                config: { type: 'data-warehouse-table', table_name: 'postgres.table_1', filters: { properties: [] } },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'non data-warehouse-table config returns null',
                config: { type: 'event', filters: {} },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(getTriggerType().validate!(config as any)).toEqual(expected)
        })
    })

    it('is gated behind the CDP_DWH_TABLE_SOURCE feature flag', () => {
        expect(getTriggerType().featureFlag).toBe('cdp-dwh-table-source')
    })

    it('buildConfig produces a config recognized by matchConfig', () => {
        const triggerType = getTriggerType()
        const config = triggerType.buildConfig()
        expect(config.type).toBe('data-warehouse-table')
        expect(triggerType.matchConfig!(config)).toBe(true)
    })
})
