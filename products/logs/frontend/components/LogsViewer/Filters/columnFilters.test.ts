import * as fs from 'fs'
import * as path from 'path'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { COLUMN_FILTER_KEYS, pinColumnFilters } from './columnFilters'

const filter = (key: string, type: PropertyFilterType): UniversalFiltersGroup['values'][number] =>
    ({ key, type, operator: PropertyOperator.Exact, value: ['x'] }) as UniversalFiltersGroup['values'][number]

const group = (...values: UniversalFiltersGroup['values']): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values,
})

describe('pinColumnFilters', () => {
    // A column key picked from the Log attributes tab arrives typed `log_attribute`, so the query reads
    // a missing attribute map entry -> zero rows. These keys must resolve to `log`. A resource attribute
    // of the same name is a distinct field, and any other key keeps the type it was picked under.
    it.each<[string, PropertyFilterType, PropertyFilterType]>([
        ['service_name', PropertyFilterType.LogAttribute, PropertyFilterType.Log],
        ['severity_level', PropertyFilterType.LogAttribute, PropertyFilterType.Log],
        ['service_name', PropertyFilterType.LogResourceAttribute, PropertyFilterType.LogResourceAttribute],
        ['service_name', PropertyFilterType.Log, PropertyFilterType.Log],
        ['env', PropertyFilterType.LogAttribute, PropertyFilterType.LogAttribute],
        ['env', PropertyFilterType.LogResourceAttribute, PropertyFilterType.LogResourceAttribute],
        ['trace_id', PropertyFilterType.LogAttribute, PropertyFilterType.LogAttribute],
    ])('resolves %s typed %s to %s', (key, type, expected) => {
        const pinned = pinColumnFilters(group(group(filter(key, type))))
        expect(pinned).toEqual(group(group(filter(key, expected))))
    })

    it('passes a malformed entry through instead of throwing', () => {
        const malformed = group(null as unknown as UniversalFiltersGroup['values'][number])
        expect(pinColumnFilters(malformed)).toBe(malformed)
    })

    // COLUMN_FILTER_KEYS hand-mirrors the backend `COLUMN_FILTER_FACET_FIELDS` dict. If the backend adds
    // a column filter key without updating the frontend set, an attribute-tab pick of that key would
    // silently return zero rows again. Parse the backend keys and lock them in step.
    it('stays in sync with the backend COLUMN_FILTER_FACET_FIELDS dict', () => {
        const runnerPath = path.resolve(__dirname, '../../../../backend/logs_query_runner.py')
        const source = fs.readFileSync(runnerPath, 'utf8')
        const block = source.match(/^COLUMN_FILTER_FACET_FIELDS[^{]*\{([^}]*)\}/m)?.[1] ?? ''
        const backendKeys = [...block.matchAll(/["']([^"']+)["']\s*:/g)].map((m) => m[1])
        // Non-empty guards that the dict was actually found and parsed, not silently empty.
        expect(backendKeys.length).toBeGreaterThan(0)
        expect(new Set(backendKeys)).toEqual(COLUMN_FILTER_KEYS)
    })
})
