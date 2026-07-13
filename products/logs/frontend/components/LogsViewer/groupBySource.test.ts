import * as fs from 'fs'
import * as path from 'path'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { GROUPABLE_COLUMN_KEYS, resolveGroupBySource } from './groupBySource'

describe('resolveGroupBySource', () => {
    // A recent for a top-level column is recorded under LogAttributes (the search bar stores it as
    // filter type `log`), so trusting the group would send source `log` and the aggregation reads a
    // missing attribute -> empty results. These keys must resolve to `column` regardless of group.
    it.each<[string, TaxonomicFilterGroupType, GroupBySourceEnumApi]>([
        ['severity_level', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['trace_id', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['span_id', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['severity_level', TaxonomicFilterGroupType.Logs, 'column'],
        ['some.attribute', TaxonomicFilterGroupType.LogAttributes, 'log'],
        ['host.name', TaxonomicFilterGroupType.LogResourceAttributes, 'resource'],
        ['some.attribute', TaxonomicFilterGroupType.Logs, 'column'],
    ])('resolves %s from %s to %s', (key, groupType, expected) => {
        expect(resolveGroupBySource(key, groupType)).toBe(expected)
    })

    // GROUPABLE_COLUMN_KEYS hand-mirrors the backend `GROUPABLE_COLUMNS` dict. If the backend adds or
    // removes a groupable column without updating the frontend set, a recent for that key would route
    // to the wrong source and silently return no groups. Parse the backend keys and lock them in step.
    it('stays in sync with the backend GROUPABLE_COLUMNS dict', () => {
        const runnerPath = path.resolve(__dirname, '../../../backend/group_by_query_runner.py')
        const source = fs.readFileSync(runnerPath, 'utf8')
        const block = source.match(/GROUPABLE_COLUMNS[^{]*\{([^}]*)\}/)?.[1] ?? ''
        const backendKeys = [...block.matchAll(/["']([^"']+)["']\s*:/g)].map((m) => m[1])
        // Non-empty guards that the dict was actually found and parsed, not silently empty.
        expect(backendKeys.length).toBeGreaterThan(0)
        expect(new Set(backendKeys)).toEqual(GROUPABLE_COLUMN_KEYS)
    })
})
