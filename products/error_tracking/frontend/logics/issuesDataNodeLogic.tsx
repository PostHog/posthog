import { actions, afterMount, connect, kea, listeners, path, props, selectors } from 'kea'
import posthog from 'posthog-js'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingIssue, ErrorTrackingQuery } from '~/queries/schema/schema-general'

import { issueActionsLogic } from '../components/IssueActions/issueActionsLogic'
import { mergeIssues } from '../utils'
import { batchSpikeEventsLogic } from './batchSpikeEventsLogic'
import type { issuesDataNodeLogicType } from './issuesDataNodeLogicType'

export interface IssuesDataNodeLogicProps {
    query: DataNodeLogicProps['query']
    key: DataNodeLogicProps['key']
}

export const issuesDataNodeLogic = kea<issuesDataNodeLogicType>([
    path(['products', 'error_tracking', 'logics', 'issuesDataNodeLogic']),
    props({} as IssuesDataNodeLogicProps),

    connect(({ key, query }: IssuesDataNodeLogicProps) => {
        const nodeLogic = dataNodeLogic({ key, query, refresh: 'blocking' })
        return {
            values: [nodeLogic, ['response', 'responseLoading'], issueActionsLogic, ['needsReload']],
            actions: [
                nodeLogic,
                ['setResponse', 'loadData', 'loadDataSuccess', 'loadDataFailure', 'cancelQuery'],
                batchSpikeEventsLogic,
                ['loadSpikeEventsForIssues'],
                issueActionsLogic,
                [
                    'mergeIssues',
                    'resolveIssues',
                    'suppressIssues',
                    'activateIssues',
                    'assignIssues',
                    'updateIssueAssignee',
                    'updateIssueStatus',
                    'mutationSuccess',
                    'mutationFailure',
                    'clearNeedsReload',
                ],
            ],
        }
    }),

    actions({
        reloadData: () => ({}),
    }),

    selectors({
        results: [
            (s) => [s.response],
            (response): ErrorTrackingIssue[] => (response && 'results' in response ? response.results : []),
        ],
    }),

    listeners(({ values, actions, props, cache }) => ({
        loadData: () => {
            cache.loadStartTime = performance.now()
        },
        reloadData: () => {
            actions.loadData('force_blocking')
        },
        loadDataSuccess: () => {
            const durationMs = cache.loadStartTime != null ? Math.round(performance.now() - cache.loadStartTime) : null

            const response = values.response as Record<string, any> | null
            const results = response && 'results' in response ? response.results : []
            const query = props.query as Record<string, any>
            const filterGroups = query?.filterGroup?.values ?? []
            const filterCount = filterGroups.reduce(
                (count: number, group: any) => count + (group?.values?.length ?? 0),
                0
            )
            const sortBy = query?.orderBy ?? null
            const sortDirection = query?.orderDirection ?? null
            const isV3 = query?.useQueryV3 ?? false
            const eventName = isV3 ? 'error_tracking_issue_list_loaded_v3' : 'error_tracking_issue_list_loaded'
            posthog.capture(eventName, {
                duration_ms: durationMs,
                result_count: (results as ErrorTrackingIssue[]).length,
                is_cached: response?.is_cached ?? null,
                filter_count: filterCount,
                sort_by: sortBy,
                sort_direction: sortDirection,
                assignee_filter: !!query?.assignee,
                status_filter: query?.status ?? null,
            })

            const issueIds = (results as ErrorTrackingIssue[]).map((issue) => issue.id).filter(Boolean)
            if (issueIds.length > 0) {
                const dateRange = (props.query as ErrorTrackingQuery).dateRange
                actions.loadSpikeEventsForIssues(issueIds, dateRange)
            }
        },
        // optimistically update local results
        mergeIssues: ({ ids }) => {
            const { results } = values

            const [primaryId, ...sourceIds] = ids
            const primaryIssue = results.find(({ id }) => id === primaryId)
            const sourceIssues = results.filter(({ id }) => sourceIds.includes(id))

            if (primaryIssue && sourceIssues.length > 0) {
                const mergedIssue = mergeIssues(primaryIssue, sourceIssues)

                actions.setResponse({
                    ...values.response,
                    results: results
                        .filter(({ id }) => !sourceIds.includes(id))
                        .map((issue) => (issue.id === primaryIssue.id ? mergedIssue : issue)),
                })
            }
        },
        resolveIssues: ({ ids }) => {
            const { results } = values
            actions.setResponse({
                ...values.response,
                results: results.map((issue) => {
                    if (ids.includes(issue.id)) {
                        return { ...issue, status: 'resolved' }
                    }
                    return issue
                }),
            })
        },
        suppressIssues: ({ ids }) => {
            const { results } = values
            actions.setResponse({
                ...values.response,
                results: results.map((issue) => {
                    if (ids.includes(issue.id)) {
                        return { ...issue, status: 'suppressed' }
                    }
                    return issue
                }),
            })
        },
        activateIssues: ({ ids }) => {
            const { results } = values
            actions.setResponse({
                ...values.response,
                results: results.map((issue) => {
                    if (ids.includes(issue.id)) {
                        return { ...issue, status: 'active' }
                    }
                    return issue
                }),
            })
        },

        assignIssues: ({ ids, assignee }) => {
            const { results } = values
            actions.setResponse({
                ...values.response,
                results: results.map((issue) =>
                    // replace primary issue
                    ids.includes(issue.id) ? { ...issue, assignee } : issue
                ),
            })
        },

        updateIssueAssignee: ({ id, assignee }) => {
            const response = values.response
            if (response) {
                const results = ('results' in response ? response.results : []) as ErrorTrackingIssue[]
                const recordIndex = results.findIndex((r) => r.id === id)
                if (recordIndex > -1) {
                    const issue = { ...results[recordIndex], assignee }
                    results.splice(recordIndex, 1, issue)
                    // optimistically update local results
                    actions.setResponse({ ...response, results: results })
                }
            }
        },

        updateIssueStatus: ({ id, status }) => {
            const response = values.response
            if (response) {
                const results = ('results' in response ? response.results : []) as ErrorTrackingIssue[]
                const recordIndex = results.findIndex((r) => r.id === id)
                if (recordIndex > -1) {
                    const issue = { ...results[recordIndex], status }
                    results.splice(recordIndex, 1, issue)
                    // optimistically update local results
                    actions.setResponse({ ...response, results: results })
                }
            }
        },

        mutationSuccess: () => {
            // in v3 when mutation succeeds, phantom gets added (which is injected into the query) so the query reloads
            // in v1 when mutation succeeds, we need to reload the data manually
            const query = props.query as Record<string, any> | null
            if (query?.useQueryV3) {
                return
            }
            actions.reloadData()
        },
        mutationFailure: () => actions.reloadData(),
    })),

    afterMount(({ values, actions, cache }) => {
        cache.loadStartTime = performance.now()
        if (values.needsReload) {
            actions.clearNeedsReload()
            actions.reloadData()
        }
    }),
])
