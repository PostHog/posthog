import equal from 'fast-deep-equal'
import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Params } from 'scenes/sceneTypes'

import { DateRange } from '~/queries/schema/schema-general'

import { syncSearchParams, updateSearchParams } from '../../utils'
import type { breakdownFiltersLogicType } from './breakdownFiltersLogicType'
import { DEFAULT_DATE_RANGE, DEFAULT_TEST_ACCOUNT } from './consts'

export const breakdownFiltersLogic = kea<breakdownFiltersLogicType>([
    path(['products', 'error_tracking', 'components', 'Breakdowns', 'breakdownFiltersLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setFilterOpen: (filterOpen: boolean) => ({ filterOpen }),
    }),
    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        filterTestAccounts: [
            DEFAULT_TEST_ACCOUNT as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        filterOpen: [
            false as boolean,
            {
                setFilterOpen: (_, { filterOpen }) => filterOpen,
            },
        ],
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.dateRange && !equal(params.dateRange, values.dateRange)) {
                actions.setDateRange(params.dateRange)
            }
            if (params.filterTestAccounts && !equal(params.filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(params.filterTestAccounts)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'filterTestAccounts', values.filterTestAccounts, DEFAULT_TEST_ACCOUNT)
                updateSearchParams(params, 'dateRange', values.dateRange, DEFAULT_DATE_RANGE)
                return params
            })
        }

        return {
            setDateRange: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),
])
