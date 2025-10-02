import equal from 'fast-deep-equal'
import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Params } from 'scenes/sceneTypes'

import { ErrorTrackingIssue, ErrorTrackingQuery } from '~/queries/schema/schema-general'

import { syncSearchParams, updateSearchParams } from '../../utils'
import type { issueQueryOptionsLogicType } from './issueQueryOptionsLogicType'

export type ErrorTrackingQueryOrderBy = ErrorTrackingQuery['orderBy']
export type ErrorTrackingQueryOrderDirection = ErrorTrackingQuery['orderDirection']
export type ErrorTrackingQueryAssignee = ErrorTrackingQuery['assignee']
export type ErrorTrackingQueryStatus = ErrorTrackingQuery['status']

const DEFAULT_ORDER_BY = 'last_seen'
const DEFAULT_ORDER_DIRECTION = 'DESC'
const DEFAULT_ASSIGNEE = null
const DEFAULT_STATUS = 'active'

export const issueQueryOptionsLogic = kea<issueQueryOptionsLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueQueryOptions', 'issueQueryOptionsLogic']),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingQueryOrderDirection) => ({ orderDirection }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setStatus: (status: ErrorTrackingQuery['status']) => ({ status }),
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
                actions.setOrderBy(params.orderBy)
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
