import { actions, connect, kea, listeners, path, props } from 'kea'

import {
    issueFiltersLogic,
    IssueFiltersLogicProps,
} from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

export type PropertyValueFilterLogicProps = {
    issueFiltersLogicKey?: IssueFiltersLogicProps['logicKey']
}

export const propertyValueFilterLogic = kea([
    path(['products', 'error_tracking', 'components', 'ExceptionCard', 'propertyValueFilterLogic']),
    props({} as PropertyValueFilterLogicProps),
    connect((props) => ({
        values: [issueFiltersLogic({ logicKey: props.issueFiltersLogicKey ?? '' }), ['filterGroup']],
        actions: [issueFiltersLogic({ logicKey: props.issueFiltersLogicKey ?? '' }), ['setFilterGroup']],
    })),
    actions({
        filterByPropertyValue: (key: string, value: string | number | boolean) => ({ key, value }),
    }),
    listeners(({ values, actions, props }) => ({
        filterByPropertyValue: ({ key, value }) => {
            if (!props.issueFiltersLogicKey) {
                return
            }

            const firstGroup = values.filterGroup.values[0] as UniversalFiltersGroup
            const hasMatchingFilter = firstGroup.values.some((filter) => {
                const propertyFilter = filter as AnyPropertyFilter
                return (
                    propertyFilter?.type === PropertyFilterType.Event &&
                    propertyFilter?.operator === PropertyOperator.Exact &&
                    propertyFilter?.key === key &&
                    Array.isArray(propertyFilter?.value) &&
                    propertyFilter.value.length === 1 &&
                    propertyFilter.value[0] === value
                )
            })
            if (hasMatchingFilter) {
                return
            }

            actions.setFilterGroup({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        ...firstGroup,
                        values: [
                            ...firstGroup.values,
                            {
                                key,
                                type: PropertyFilterType.Event,
                                operator: PropertyOperator.Exact,
                                value: [value],
                            },
                        ],
                    },
                ],
            })
        },
    })),
])
