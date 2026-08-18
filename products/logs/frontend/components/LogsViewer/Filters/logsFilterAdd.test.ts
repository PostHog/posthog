import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { indexOfFilterOn, logsSelection, mergeFilterIntoValues, selectionTarget } from './logsFilterAdd'

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
            // The type is half the identity: a resource attribute named service_name filters a
            // different field from the service_name column, so the two must not fold together.
            [
                'a different property type',
                logFilter('service_name', PropertyOperator.Exact, ['api']),
                attributeFilter('service_name', PropertyOperator.Exact, ['worker']),
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

    describe('indexOfFilterOn', () => {
        const values = [
            logFilter('message', PropertyOperator.IContains, 'timeout'),
            logFilter('service_name', PropertyOperator.IsNot, ['api']),
        ]

        it.each<[string, PropertyFilterType, string, number]>([
            ['the filter on that attribute', PropertyFilterType.Log, 'service_name', 1],
            ['whatever operator it uses', PropertyFilterType.Log, 'message', 0],
            ['no match for another type', PropertyFilterType.LogAttribute, 'service_name', -1],
            ['no match for another key', PropertyFilterType.Log, 'severity_level', -1],
        ])('finds %s', (_, type, key, expected) => {
            expect(indexOfFilterOn(values, { type, key })).toEqual(expected)
        })

        it('returns -1 when the selection maps to no attribute', () => {
            expect(indexOfFilterOn(values, null)).toEqual(-1)
        })
    })

    // Which branch a dropdown item takes is the whole fix: a recent carrying a complete filter has to
    // reconcile, and a bare key on an already-filtered attribute has to reuse that filter.
    describe('logsSelection', () => {
        const recentItem = (propertyFilter: unknown): Record<string, any> => ({
            name: 'service_name',
            propertyFilterType: PropertyFilterType.Log,
            _recentContext: { sourceGroupType: TaxonomicFilterGroupType.Logs, propertyFilter },
        })
        const standing = [logFilter('service_name', PropertyOperator.IsNot, ['api'])]

        it('merges a recent that carries a complete filter', () => {
            const complete = {
                key: 'service_name',
                type: PropertyFilterType.Log,
                operator: PropertyOperator.Exact,
                value: ['api'],
            }

            expect(logsSelection(standing, LOGS_GROUP, 'service_name', recentItem(complete))).toEqual({
                kind: 'merge',
                filter: complete,
            })
        })

        it('treats a recent with no value as a bare key, since there is nothing to merge', () => {
            const bare = { key: 'service_name', type: PropertyFilterType.Log, operator: PropertyOperator.Exact }

            expect(logsSelection(standing, LOGS_GROUP, 'service_name', recentItem(bare))).toEqual({
                kind: 'focus',
                index: 0,
            })
        })

        it("routes the Logs group's free-text item to the caller that builds and records it", () => {
            const item = { key: 'message', value: 'timeout', propertyFilterType: PropertyFilterType.Log }

            expect(logsSelection([], LOGS_GROUP, 'message', item)).toEqual({ kind: 'valueItem' })
        })

        it('focuses the filter already on the picked attribute', () => {
            const item = { name: 'service_name', propertyFilterType: PropertyFilterType.Log }

            expect(logsSelection(standing, LOGS_GROUP, 'service_name', item)).toEqual({ kind: 'focus', index: 0 })
        })

        it('adds a new filter when that attribute has none', () => {
            const item = { name: 'level', propertyFilterType: PropertyFilterType.LogAttribute }

            expect(logsSelection(standing, LOG_ATTRIBUTES_GROUP, 'level', item)).toEqual({ kind: 'new' })
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
