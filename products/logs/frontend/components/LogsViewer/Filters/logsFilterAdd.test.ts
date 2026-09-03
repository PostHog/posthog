import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { LogsFilterTarget } from './logsFilterAdd'
import { appliedEqualityTarget, logsSelection, mergeFilterIntoValues, selectionTarget } from './logsFilterAdd'

const LOGS_GROUP = { name: 'Logs', type: TaxonomicFilterGroupType.Logs } as TaxonomicFilterGroup
const LOG_ATTRIBUTES_GROUP = {
    name: 'Log attributes',
    type: TaxonomicFilterGroupType.LogAttributes,
} as TaxonomicFilterGroup

type FilterEntry = UniversalFiltersGroup['values'][number]

const logFilter = (key: string, operator: PropertyOperator, value?: string | string[]): FilterEntry =>
    ({ key, type: PropertyFilterType.Log, operator, value }) as FilterEntry

const attributeFilter = (key: string, operator: PropertyOperator, value?: string | string[]): FilterEntry =>
    ({ key, type: PropertyFilterType.LogAttribute, operator, value }) as FilterEntry

const resourceFilter = (key: string, operator: PropertyOperator, value?: string | string[]): FilterEntry =>
    ({ key, type: PropertyFilterType.LogResourceAttribute, operator, value }) as FilterEntry

/** Applies a pick that must reconcile, failing loudly if the decision came out as something else. */
const applyPick = (values: FilterEntry[], group: TaxonomicFilterGroup, item: Record<string, any>): FilterEntry[] => {
    const selection = logsSelection(values, group, 'service_name', item)
    if (selection.kind !== 'merge') {
        throw new Error(`expected a merge, got ${selection.kind}`)
    }
    return mergeFilterIntoValues(values, selection.filter)
}

describe('logsFilterAdd', () => {
    describe('mergeFilterIntoValues', () => {
        // Picking a filter that contradicts a standing one used to leave both in the group, which ANDs
        // `IN (x)` with `NOT IN (x)` and returns no logs at all.
        it('cancels the opposite polarity for the value being added', () => {
            const existing = [logFilter('service_name', PropertyOperator.IsNot, ['posthog-db-1'])]
            expect(
                mergeFilterIntoValues(existing, logFilter('service_name', PropertyOperator.Exact, ['posthog-db-1']))
            ).toEqual([logFilter('service_name', PropertyOperator.Exact, ['posthog-db-1'])])
        })

        it('keeps the values of the opposite polarity it was not asked about', () => {
            const existing = [logFilter('service_name', PropertyOperator.IsNot, ['api', 'worker'])]
            expect(mergeFilterIntoValues(existing, logFilter('service_name', PropertyOperator.Exact, ['api']))).toEqual(
                [
                    logFilter('service_name', PropertyOperator.IsNot, ['worker']),
                    logFilter('service_name', PropertyOperator.Exact, ['api']),
                ]
            )
        })

        it('merges into the filter already holding that polarity rather than adding a second one', () => {
            const existing = [logFilter('service_name', PropertyOperator.Exact, ['api'])]
            expect(
                mergeFilterIntoValues(existing, logFilter('service_name', PropertyOperator.Exact, ['worker']))
            ).toEqual([logFilter('service_name', PropertyOperator.Exact, ['api', 'worker'])])
        })

        it('does not repeat a value the filter already carries', () => {
            const existing = [logFilter('service_name', PropertyOperator.Exact, ['api'])]
            expect(mergeFilterIntoValues(existing, logFilter('service_name', PropertyOperator.Exact, ['api']))).toEqual(
                [logFilter('service_name', PropertyOperator.Exact, ['api'])]
            )
        })

        it('normalizes a scalar value into the list it merges into', () => {
            const existing = [logFilter('service_name', PropertyOperator.Exact, 'api')]
            expect(
                mergeFilterIntoValues(existing, logFilter('service_name', PropertyOperator.Exact, 'worker'))
            ).toEqual([logFilter('service_name', PropertyOperator.Exact, ['api', 'worker'])])
        })

        it.each<[string, FilterEntry, FilterEntry]>([
            // A resource attribute maps to a group of its own, so its type is never in doubt and a
            // resource attribute named service_name stays separate from the service_name column.
            [
                'a resource attribute of the same name',
                logFilter('service_name', PropertyOperator.Exact, ['api']),
                resourceFilter('service_name', PropertyOperator.Exact, ['worker']),
            ],
            [
                'a different key',
                logFilter('service_name', PropertyOperator.Exact, ['api']),
                logFilter('severity_level', PropertyOperator.Exact, ['error']),
            ],
        ])('leaves %s alone', (_, existing, incoming) => {
            expect(mergeFilterIntoValues([existing], incoming)).toEqual([existing, incoming])
        })

        // Two substring matches on one attribute are a legitimate AND, unlike two equality filters.
        it('appends a second contains filter on the same attribute', () => {
            const existing = [logFilter('message', PropertyOperator.IContains, 'timeout')]
            const incoming = logFilter('message', PropertyOperator.IContains, 'retry')
            expect(mergeFilterIntoValues(existing, incoming)).toEqual([...existing, incoming])
        })

        // Merging compares values as strings, but a filter keeps whatever type it stored.
        it('leaves a non-string value alone when merging into it', () => {
            const numeric = {
                key: 'status',
                type: PropertyFilterType.Log,
                operator: PropertyOperator.Exact,
                value: [500],
            } as unknown as FilterEntry
            const incoming = {
                key: 'status',
                type: PropertyFilterType.Log,
                operator: PropertyOperator.Exact,
                value: ['503'],
            } as unknown as FilterEntry

            expect(mergeFilterIntoValues([numeric], incoming)).toEqual([
                { key: 'status', type: PropertyFilterType.Log, operator: PropertyOperator.Exact, value: [500, '503'] },
            ])
        })

        it('drops an identical repeat of a non-equality filter', () => {
            const existing = [logFilter('message', PropertyOperator.IContains, 'timeout')]
            expect(
                mergeFilterIntoValues(existing, logFilter('message', PropertyOperator.IContains, 'timeout'))
            ).toEqual(existing)
        })

        it('appends a value-less filter, which has nothing to merge on yet', () => {
            const existing = [logFilter('service_name', PropertyOperator.Exact, ['api'])]
            const incoming = logFilter('severity_level', PropertyOperator.Exact, undefined)
            expect(mergeFilterIntoValues(existing, incoming)).toEqual([...existing, incoming])
        })

        it('carries a nested group through untouched', () => {
            const nested = {
                type: 'OR',
                values: [attributeFilter('distinct_id', PropertyOperator.Exact, ['7'])],
            } as unknown as FilterEntry
            const incoming = logFilter('service_name', PropertyOperator.Exact, ['api'])
            expect(mergeFilterIntoValues([nested], incoming)).toEqual([nested, incoming])
        })
    })

    describe('appliedEqualityTarget', () => {
        const values = [
            logFilter('message', PropertyOperator.IContains, 'timeout'),
            logFilter('service_name', PropertyOperator.IsNot, ['api']),
        ]

        it.each<[string, PropertyFilterType, string, LogsFilterTarget | null]>([
            [
                'the equality filter on that attribute',
                PropertyFilterType.Log,
                'service_name',
                { key: 'service_name', type: PropertyFilterType.Log },
            ],
            [
                'a log attribute pick matching the column of that name',
                PropertyFilterType.LogAttribute,
                'service_name',
                { key: 'service_name', type: PropertyFilterType.Log },
            ],
            [
                'no match for a resource attribute of that name',
                PropertyFilterType.LogResourceAttribute,
                'service_name',
                null,
            ],
            ['no match for another key', PropertyFilterType.Log, 'severity_level', null],
            // A contains filter is an independent predicate, so picking that attribute again adds one
            // rather than editing the filter already there.
            ['no match for a contains filter', PropertyFilterType.Log, 'message', null],
        ])('finds %s', (_, type, key, expected) => {
            expect(appliedEqualityTarget(values, { type, key })).toEqual(expected)
        })

        it('returns null when the selection maps to no attribute', () => {
            expect(appliedEqualityTarget(values, null)).toBeNull()
        })
    })

    // The reported sequences, in both orders. A recent is recorded under the Log attributes group even
    // when it came from a `log` column filter, so the group cannot decide the attribute.
    describe('picking a recent against an applied filter', () => {
        const recentOf = (
            operator: PropertyOperator,
            type: PropertyFilterType = PropertyFilterType.Log
        ): Record<string, any> => ({
            name: 'service_name',
            _recentContext: {
                sourceGroupType: TaxonomicFilterGroupType.LogAttributes,
                sourceGroupName: 'Log attributes',
                sourceValue: 'service_name',
                propertyFilter: { key: 'service_name', type, operator, value: ['posthog-db-1'] },
            },
        })
        const applied = (operator: PropertyOperator): FilterEntry =>
            ({ key: 'service_name', type: PropertyFilterType.Log, operator, value: ['posthog-db-1'] }) as FilterEntry
        const applyRecent = (values: FilterEntry[], item: Record<string, any>): FilterEntry[] =>
            applyPick(values, LOG_ATTRIBUTES_GROUP, item)

        it.each<[string, PropertyOperator, PropertyOperator]>([
            ['an applied = replaced by a picked ≠', PropertyOperator.Exact, PropertyOperator.IsNot],
            ['an applied ≠ replaced by a picked =', PropertyOperator.IsNot, PropertyOperator.Exact],
        ])('leaves one filter for %s', (_, appliedOperator, pickedOperator) => {
            expect(applyRecent([applied(appliedOperator)], recentOf(pickedOperator))).toEqual([applied(pickedOperator)])
        })

        // A recent for a `log` column filter maps back to `log_attribute`, so before this the picked
        // filter targeted an attribute of the same name and landed beside the column filter.
        it('reuses the applied field when the picked type disagrees on the same key', () => {
            const result = applyRecent(
                [applied(PropertyOperator.IsNot)],
                recentOf(PropertyOperator.Exact, PropertyFilterType.LogAttribute)
            )

            expect(result).toEqual([applied(PropertyOperator.Exact)])
        })

        // Picking both polarities straight from recents, with no facet-rail click involved.
        it('leaves one filter when both polarities are picked in turn', () => {
            const first = applyRecent([], recentOf(PropertyOperator.Exact))
            expect(first).toEqual([applied(PropertyOperator.Exact)])

            expect(applyRecent(first, recentOf(PropertyOperator.IsNot))).toEqual([applied(PropertyOperator.IsNot)])
        })

        it('keeps a filter on a genuinely different key', () => {
            const other = logFilter('severity_level', PropertyOperator.Exact, ['error'])
            const result = applyRecent([other, applied(PropertyOperator.IsNot)], recentOf(PropertyOperator.Exact))

            expect(result).toEqual([other, applied(PropertyOperator.Exact)])
        })

        // The bare-key row the picker derives from a complete recent. Opening the applied filter has to
        // leave its value alone, so the reported "adds an empty second chip" cannot happen.
        it.each<[string, PropertyOperator]>([
            ['an applied =', PropertyOperator.Exact],
            ['an applied ≠', PropertyOperator.IsNot],
        ])('opens %s when the bare key is picked, without touching its value', (_, operator) => {
            const values = [applied(operator)]
            const bare = {
                name: 'service_name',
                _recentContext: {
                    sourceGroupType: TaxonomicFilterGroupType.LogAttributes,
                    sourceGroupName: 'Log attributes',
                    sourceValue: 'service_name',
                },
            }

            expect(logsSelection(values, LOG_ATTRIBUTES_GROUP, 'service_name', bare)).toEqual({
                kind: 'focus',
                target: { key: 'service_name', type: PropertyFilterType.Log },
            })
            expect(values).toEqual([applied(operator)])
        })
    })

    describe('rows the search matched on a value', () => {
        // Those rows carry the value as matchedValue, and the shared builder pre-fills it. Read as a
        // bare key instead, the pick was dropped and the standing filter merely reopened.
        const valueRow = {
            name: 'service_name',
            propertyFilterType: PropertyFilterType.Log,
            matchedOn: 'value',
            matchedValue: 'posthog-web',
        }

        it.each<[string, FilterEntry[]]>([
            ['against the applied filter', [logFilter('service_name', PropertyOperator.IsNot, ['posthog-web'])]],
            ['when the attribute has no filter yet', []],
        ])('reconciles the matched value %s', (_, applied) => {
            expect(applyPick(applied, LOG_ATTRIBUTES_GROUP, valueRow)).toEqual([
                logFilter('service_name', PropertyOperator.Exact, ['posthog-web']),
            ])
        })
    })

    describe('selectionTarget', () => {
        it("prefers the item's own property-filter type over its group's", () => {
            const item = { propertyFilterType: PropertyFilterType.LogResourceAttribute }

            expect(selectionTarget(LOGS_GROUP, 'service.name', item)).toEqual({
                type: PropertyFilterType.LogResourceAttribute,
                key: 'service.name',
            })
        })

        it('falls back to the type its group maps to', () => {
            expect(selectionTarget(LOGS_GROUP, 'service_name', {})).toEqual({
                type: PropertyFilterType.Log,
                key: 'service_name',
            })
        })

        it('has no target when the selection carries no key', () => {
            expect(selectionTarget(LOGS_GROUP, null, {})).toBeNull()
        })
    })
})
