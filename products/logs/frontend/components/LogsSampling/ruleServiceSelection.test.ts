import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { ruleServiceNames, withRuleServiceNames } from './ruleServiceSelection'

const emptyGroup = (): UniversalFiltersGroup => ({ type: FilterLogicalOperator.And, values: [] })

const attributeChip = {
    key: 'k8s.namespace.name',
    type: PropertyFilterType.LogResourceAttribute,
    operator: PropertyOperator.Exact,
    value: ['contour'],
}

describe('ruleServiceSelection', () => {
    it('round-trips a selection through the exact shape the matcher and query builder read', () => {
        // The contract with `filter-group-match.ts` and `LogsFilterBuilder`: a service selection is
        // one `exact` filter under the column key. Any drift in key, type, or operator makes the
        // rule silently stop scoping by service, with nothing in the UI saying so.
        const group = withRuleServiceNames(emptyGroup(), ['contour', 'billing'])

        expect(group.values).toEqual([
            {
                key: 'service_name',
                type: PropertyFilterType.Log,
                operator: PropertyOperator.Exact,
                value: ['contour', 'billing'],
            },
        ])
        expect(ruleServiceNames(group)).toEqual(['contour', 'billing'])
    })

    it('reads the editor group directly, not the viewer wrapper', () => {
        // The rule editors hold the inner group; facetFilters' helpers expect it wrapped one level
        // deeper. Getting the shape wrong fails silently: the dropdown reads "All services" while a
        // service filter chip sits right below it.
        const group: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'service_name',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['contour'],
                },
            ],
        }
        expect(ruleServiceNames(group)).toEqual(['contour'])
    })

    it('replaces the selection while carrying every other filter through untouched', () => {
        const withOthers = withRuleServiceNames({ type: FilterLogicalOperator.And, values: [attributeChip] }, [
            'contour',
        ])
        const reselected = withRuleServiceNames(withOthers, ['billing'])

        expect(ruleServiceNames(reselected)).toEqual(['billing'])
        expect(reselected.values).toContainEqual(attributeChip)
        expect(reselected.values).toHaveLength(2)
    })

    it('clearing the selection removes the filter so the rule applies to all services', () => {
        const cleared = withRuleServiceNames(withRuleServiceNames(emptyGroup(), ['contour']), [])
        expect(cleared.values).toEqual([])
        expect(ruleServiceNames(cleared)).toEqual([])
    })

    it('leaves a hand-edited service exclusion in place', () => {
        const exclusion = {
            key: 'service_name',
            type: PropertyFilterType.Log,
            operator: PropertyOperator.IsNot,
            value: ['noisy-svc'],
        }
        const group = withRuleServiceNames({ type: FilterLogicalOperator.And, values: [exclusion] }, ['contour'])

        expect(ruleServiceNames(group)).toEqual(['contour'])
        expect(group.values).toContainEqual(exclusion)
    })
})
