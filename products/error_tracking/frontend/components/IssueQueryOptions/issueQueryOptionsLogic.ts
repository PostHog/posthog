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
export type ErrorTrackingQueryRevenuePeriod = ErrorTrackingQuery['revenuePeriod']
export type ErrorTrackingQueryRevenueEntity = ErrorTrackingQuery['revenueEntity']
export type ErrorTrackingQueryAssignee = ErrorTrackingQuery['assignee']
export type ErrorTrackingQueryStatus = ErrorTrackingQuery['status']

const DEFAULT_ORDER_BY = 'last_seen'
const DEFAULT_ORDER_DIRECTION = 'DESC'
const DEFAULT_REVENUE_PERIOD = 'last_30_days'
const DEFAULT_REVENUE_ENTITY = 'person'
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
        setRevenueEntity: (revenueEntity: ErrorTrackingQueryRevenueEntity) => ({ revenueEntity }),
        setRevenuePeriod: (revenuePeriod: ErrorTrackingQueryRevenuePeriod) => ({ revenuePeriod }),
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
        revenuePeriod: [
            DEFAULT_REVENUE_PERIOD as ErrorTrackingQueryRevenuePeriod,
            { persist: true },
            {
                setRevenuePeriod: (_, { revenuePeriod }) => revenuePeriod,
            },
        ],
        revenueEntity: [
            DEFAULT_REVENUE_ENTITY as ErrorTrackingQueryRevenueEntity,
            { persist: true },
            {
                setRevenueEntity: (_, { revenueEntity }) => revenueEntity,
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
                revenue_entity: orderBy === 'revenue' ? values.revenueEntity : undefined,
            })
        },
        setOrderDirection: ({ orderDirection }) => {
            posthog.capture('error_tracking_issues_sorted', {
                sort_by: values.orderBy,
                sort_direction: orderDirection,
                revenue_entity: values.orderBy === 'revenue' ? values.revenueEntity : undefined,
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
                updateSearchParams(params, 'revenuePeriod', values.revenuePeriod, DEFAULT_REVENUE_PERIOD)
                updateSearchParams(params, 'revenueEntity', values.revenueEntity, DEFAULT_REVENUE_ENTITY)
                return params
            })
        }

        return {
            setOrderBy: () => buildURL(),
            setStatus: () => buildURL(),
            setAssignee: () => buildURL(),
            setRevenuePeriod: () => buildURL(),
            setRevenueEntity: () => buildURL(),
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
            if (params.revenueEntity && !equal(params.revenueEntity, values.revenueEntity)) {
                actions.setRevenueEntity(params.revenueEntity)
            }
            if (params.revenuePeriod && !equal(params.revenuePeriod, values.revenuePeriod)) {
                actions.setOrderDirection(params.revenuePeriod)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
