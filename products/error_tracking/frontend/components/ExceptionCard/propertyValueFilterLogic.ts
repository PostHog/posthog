import { actions, connect, kea, listeners, path } from 'kea'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY } from 'products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export const propertyValueFilterLogic = kea([
    path(['products', 'error_tracking', 'components', 'ExceptionCard', 'propertyValueFilterLogic']),
    connect(() => ({
        values: [issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }), ['filterGroup']],
        actions: [issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }), ['setFilterGroup']],
    })),
    actions({
        filterByPropertyValue: (key: string, value: string | number | boolean) => ({ key, value }),
    }),
    listeners(({ values, actions }) => ({
        filterByPropertyValue: ({ key, value }) => {
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
