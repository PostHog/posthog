import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { issueActionsLogic } from '../components/IssueActions/issueActionsLogic'
import { mergeIssues } from '../utils'
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
        setLoadStartTime: (startTime: number | null) => ({ startTime }),
    }),

    reducers({
        loadStartTime: [
            null as number | null,
            {
                setLoadStartTime: (_, { startTime }) => startTime,
            },
        ],
    }),

    selectors({
        results: [
            (s) => [s.response],
            (response): ErrorTrackingIssue[] => (response && 'results' in response ? response.results : []),
        ],
    }),

    listeners(({ values, actions, props }) => ({
        reloadData: () => {
            actions.loadData('force_blocking')
        },
        loadData: () => {
            actions.setLoadStartTime(performance.now())
        },
        loadDataSuccess: () => {
            const durationMs =
                values.loadStartTime !== null ? Math.round(performance.now() - values.loadStartTime) : null
            actions.setLoadStartTime(null)

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
            posthog.capture('error_tracking_issue_list_loaded', {
                duration_ms: durationMs,
                result_count: (results as ErrorTrackingIssue[]).length,
                is_cached: response?.is_cached ?? null,
                filter_count: filterCount,
                sort_by: sortBy,
                sort_direction: sortDirection,
            })
        },
        // optimistically update local results
        mergeIssues: ({ ids }) => {
            const { results } = values

            const issues = results.filter(({ id }) => ids.includes(id))
            const primaryIssue = issues.shift()

            if (primaryIssue && issues.length > 0) {
                const mergingIds = issues.map((g) => g.id)
                const mergedIssue = mergeIssues(primaryIssue, issues)

                // optimistically update local results
                actions.setResponse({
                    ...values.response,
                    results: results
                        .filter(({ id }) => !mergingIds.includes(id))
                        .map((issue) =>
                            // replace primary issue
                            mergedIssue.id === issue.id ? mergedIssue : issue
                        ),
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

        mutationSuccess: () => actions.reloadData(),
        mutationFailure: () => actions.reloadData(),
    })),

    afterMount(({ values, actions }) => {
        if (values.needsReload) {
            actions.clearNeedsReload()
            actions.reloadData()
        }
    }),
])
