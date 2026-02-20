import { afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { MaxErrorTrackingIssuePreview } from '~/queries/schema/schema-assistant-error-tracking'
import { ErrorTrackingIssue, ErrorTrackingQuery, NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import type { relatedErrorsLogicType } from './relatedErrorsLogicType'

export interface RelatedErrorsLogicProps {
    logUuid: string
    logTimestamp: string
    sessionId: string
}

export const relatedErrorsLogic = kea<relatedErrorsLogicType>([
    props({} as RelatedErrorsLogicProps),
    key((props) => props.logUuid),
    path((key) => [
        'products',
        'logs',
        'frontend',
        'components',
        'LogsViewer',
        'LogDetailsModal',
        'Tabs',
        'RelatedErrors',
        'relatedErrorsLogic',
        key,
    ]),

    loaders(({ props }) => ({
        relatedIssues: {
            __default: [] as MaxErrorTrackingIssuePreview[],
            loadRelatedIssues: async (): Promise<MaxErrorTrackingIssuePreview[]> => {
                // Handle both ISO strings and epoch timestamps (seconds or milliseconds)
                const parsed = Number(props.logTimestamp)
                const timestamp = Number.isNaN(parsed) ? dayjs(props.logTimestamp) : dayjs(parsed)

                const query: ErrorTrackingQuery = {
                    kind: NodeKind.ErrorTrackingQuery,
                    orderBy: 'last_seen',
                    dateRange: {
                        date_from: timestamp.subtract(6, 'hours').toISOString(),
                        date_to: timestamp.add(6, 'hours').toISOString(),
                    },
                    filterGroup: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$session_id',
                                        value: props.sessionId,
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                    volumeResolution: 0,
                    withAggregations: true,
                    limit: 100,
                }

                const response = await api.query(query)
                const issues = response.results as ErrorTrackingIssue[]

                return issues.map(
                    (issue): MaxErrorTrackingIssuePreview => ({
                        id: issue.id,
                        name: issue.name,
                        description: issue.description,
                        library: issue.library,
                        status: issue.status,
                        occurrences: issue.aggregations?.occurrences ?? 0,
                        sessions: issue.aggregations?.sessions ?? 0,
                        users: issue.aggregations?.users ?? 0,
                        first_seen: issue.first_seen,
                        last_seen: issue.last_seen,
                    })
                )
            },
        },
    })),

    reducers({
        relatedIssuesError: [
            null as string | null,
            {
                loadRelatedIssues: () => null,
                loadRelatedIssuesFailure: (_, { error }) => error || 'Failed to load related errors',
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRelatedIssues()
    }),
])
