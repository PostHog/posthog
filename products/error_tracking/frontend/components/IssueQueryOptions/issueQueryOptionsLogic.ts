import { actions, kea, path, reducers } from 'kea'

import { ErrorTrackingIssue, ErrorTrackingQuery } from '~/queries/schema/schema-general'

import type { issueQueryOptionsLogicType } from './issueQueryOptionsLogicType'

export type ErrorTrackingQueryOrderBy = ErrorTrackingQuery['orderBy']
export type ErrorTrackingQueryOrderDirection = ErrorTrackingQuery['orderDirection']
export type ErrorTrackingQueryAssignee = ErrorTrackingQuery['assignee']
export type ErrorTrackingQueryStatus = ErrorTrackingQuery['status']

export const ERROR_TRACKING_DEFAULT_ORDER_BY = 'last_seen'
export const ERROR_TRACKING_DEFAULT_ORDER_DIRECTION = 'DESC'
export const ERROR_TRACKING_DEFAULT_ASSIGNEE = null
export const ERROR_TRACKING_DEFAULT_STATUS = 'active'

export const issueQueryOptionsLogic = kea<issueQueryOptionsLogicType>([
    path(['scenes', 'error-tracking', 'issueQueryOptionsLogic']),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQueryOrderBy) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingQueryOrderDirection) => ({ orderDirection }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setStatus: (status: ErrorTrackingQuery['status']) => ({ status }),
    }),

    reducers({
        orderBy: [
            ERROR_TRACKING_DEFAULT_ORDER_BY as ErrorTrackingQueryOrderBy,
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        orderDirection: [
            ERROR_TRACKING_DEFAULT_ORDER_DIRECTION as ErrorTrackingQueryOrderDirection,
            { persist: true },
            {
                setOrderDirection: (_, { orderDirection }) => orderDirection,
            },
        ],
        assignee: [
            ERROR_TRACKING_DEFAULT_ASSIGNEE as ErrorTrackingQueryAssignee | null,
            { persist: true },
            {
                setAssignee: (_, { assignee }) => assignee,
            },
        ],
        status: [
            ERROR_TRACKING_DEFAULT_STATUS as ErrorTrackingQueryStatus,
            { persist: true },
            {
                setStatus: (_, { status }) => status,
            },
        ],
    }),
])
