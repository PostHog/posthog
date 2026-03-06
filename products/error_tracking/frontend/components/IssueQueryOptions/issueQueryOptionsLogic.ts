import equal from 'fast-deep-equal'
import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { Params } from 'scenes/sceneTypes'

import { ErrorTrackingIssue, ErrorTrackingQuery } from '~/queries/schema/schema-general'

import { syncSearchParams, updateSearchParams } from '../../utils'
import type { issueQueryOptionsLogicType } from './issueQueryOptionsLogicType'

export type ErrorTrackingQueryOrderBy = ErrorTrackingQuery['orderBy']
export type ErrorTrackingQueryOrderDirection = ErrorTrackingQuery['orderDirection']
export type ErrorTrackingQueryAssignee = ErrorTrackingQuery['assignee']
export type ErrorTrackingQueryStatus = ErrorTrackingQuery['status']

export const ORDER_BY_OPTIONS: Record<ErrorTrackingQueryOrderBy, string> = {
    last_seen: 'Last seen',
    first_seen: 'First seen',
    occurrences: 'Occurrences',
    users: 'Users',
    sessions: 'Sessions',
}
const DEFAULT_ORDER_BY: ErrorTrackingQueryOrderBy = 'last_seen'
const DEFAULT_ORDER_DIRECTION = 'DESC'
const DEFAULT_ASSIGNEE = null
const DEFAULT_STATUS = 'active'

export interface IssueQueryOptionsLogicProps {
    logicKey: string
}

export const issueQueryOptionsLogic = kea<issueQueryOptionsLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueQueryOptions', 'issueQueryOptionsLogic']),
    props({} as IssueQueryOptionsLogicProps),
    key(({ logicKey }) => logicKey),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingQueryOrderDirection) => ({ orderDirection }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setStatus: (status: ErrorTrackingQueryStatus) => ({ status }),
    }),

    reducers({
        orderBy: [
            DEFAULT_ORDER_BY as ErrorTrackingQueryOrderBy,
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        orderDirection: [
            DEFAULT_ORDER_DIRECTION as ErrorTrackingQueryOrderDirection,
            { persist: true },
            {
                setOrderDirection: (_, { orderDirection }) => orderDirection,
            },
        ],
        assignee: [
            DEFAULT_ASSIGNEE as ErrorTrackingQueryAssignee | null,
            { persist: true },
            {
                setAssignee: (_, { assignee }) => assignee,
            },
        ],
        status: [
            DEFAULT_STATUS as ErrorTrackingQueryStatus,
            { persist: true },
            {
                setStatus: (_, { status }) => status,
            },
        ],
    }),

    listeners(({ values }) => ({
        setOrderBy: ({ orderBy }) => {
            posthog.capture('error_tracking_issues_sorted', {
                sort_by: orderBy,
                sort_direction: values.orderDirection,
            })
        },
        setOrderDirection: ({ orderDirection }) => {
            posthog.capture('error_tracking_issues_sorted', {
                sort_by: values.orderBy,
                sort_direction: orderDirection,
            })
        },
    })),

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
                updateSearchParams(params, 'assignee', values.assignee, DEFAULT_ASSIGNEE)
                updateSearchParams(params, 'status', values.status, DEFAULT_STATUS)
                updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                updateSearchParams(params, 'orderDirection', values.orderDirection, DEFAULT_ORDER_DIRECTION)
                return params
            })
        }

        return {
            setOrderBy: () => buildURL(),
            setStatus: () => buildURL(),
            setAssignee: () => buildURL(),
            setOrderDirection: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                if (params.orderBy in ORDER_BY_OPTIONS) {
                    actions.setOrderBy(params.orderBy)
                }
            }
            if (params.status && !equal(params.status, values.status)) {
                actions.setStatus(params.status)
            }
            if (params.assignee && !equal(params.assignee, values.assignee)) {
                actions.setAssignee(params.assignee)
            }
            if (params.orderDirection && !equal(params.orderDirection, values.orderDirection)) {
                actions.setOrderDirection(params.orderDirection)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
