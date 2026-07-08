import { AttributeColumnConfig } from 'products/logs/frontend/types'

import { columnsToCustomColumns, LogsColumnConfig, migrateAttributeColumns } from './columns'

describe('logs column config', () => {
    describe('columnsToCustomColumns', () => {
        it('lowers only custom columns, in order, and never sends built-ins', () => {
            const columns: LogsColumnConfig[] = [
                { id: 'timestamp', type: 'timestamp' },
                { id: 'a', type: 'custom', expression: 'attributes.http.url' },
                { id: 'level', type: 'level' },
                { id: 'b', type: 'custom', expression: ' upper(level) ' },
                { id: 'message', type: 'message' },
            ]
            expect(columnsToCustomColumns(columns)).toEqual(['attributes.http.url', 'upper(level)'])
        })

        it.each<[string, LogsColumnConfig[]]>([
            ['no columns', []],
            ['built-ins only', [{ id: 'timestamp', type: 'timestamp' }]],
            ['custom with blank expression', [{ id: 'x', type: 'custom', expression: '   ' }]],
            ['custom with no expression', [{ id: 'x', type: 'custom' }]],
        ])('returns undefined (not []) for %s, keeping query payloads cache-identical', (_, columns) => {
            expect(columnsToCustomColumns(columns)).toBeUndefined()
        })
    })

    describe('migrateAttributeColumns', () => {
        it('orders by the legacy order field and preserves width', () => {
            // Insertion order deliberately disagrees with the order field
            const legacy: Record<string, AttributeColumnConfig> = {
                'k8s.pod': { order: 1, width: 240 },
                'http.status_code': { order: 0 },
            }
            const migrated = migrateAttributeColumns(legacy)

            expect(migrated.map((c) => c.name)).toEqual(['http.status_code', 'k8s.pod'])
            expect(migrated.map((c) => c.type)).toEqual(['custom', 'custom'])
            expect(migrated[0].width).toBeUndefined()
            expect(migrated[1].width).toBe(240)
            expect(new Set(migrated.map((c) => c.id)).size).toBe(2)
        })

        it('emits an expression that reads both maps, matching the legacy attributes-then-resource fallback', () => {
            const [migrated] = migrateAttributeColumns({ 'service.version': { order: 0 } })
            expect(migrated.expression).toBe(
                "if(mapContains(attributes, 'service.version'), attributes['service.version'], resource_attributes['service.version'])"
            )
        })

        it('escapes quotes and backslashes so keys cannot break out of the expression string', () => {
            const [migrated] = migrateAttributeColumns({ "we'ird\\key": { order: 0 } })
            expect(migrated.expression).toContain("we\\'ird\\\\key")
        })
    })
})
