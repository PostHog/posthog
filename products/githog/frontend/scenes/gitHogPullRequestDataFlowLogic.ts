import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPullRequestDataFlowLogicType } from './gitHogPullRequestDataFlowLogicType'

export interface GitHogPullRequestDataFlowLogicProps {
    owner: string
    name: string
    number: number
}

export interface GitHogDataFlowStep {
    id: string
    title: string
    file: string
    detail: string
}

export interface GitHogFlowNode {
    id: string
    label: string
    file: string
    detail: string
    kind: string
}

export interface GitHogFlowEdge {
    source: string
    target: string
    label: string
}

export interface GitHogFlowGraph {
    nodes: GitHogFlowNode[]
    edges: GitHogFlowEdge[]
}

export interface GitHogDataFlow {
    repository: string
    pr_number: number
    head_sha: string
    base_sha: string
    flow_before: GitHogFlowGraph
    flow_after: GitHogFlowGraph
    steps_before: GitHogDataFlowStep[]
    steps_after: GitHogDataFlowStep[]
    summary: string
    truncated: boolean
    files_total: number
    files_with_content: number
    cached: boolean
    computed_at: string
}

export type DataFlowView = 'graphs' | 'diff' | 'steps'

// Survives kea unmount/remount cycles (e.g. React StrictMode dev double-mount). The Refresh
// button bypasses this set explicitly by calling refreshDataFlow → loadDataFlow({refresh:true}).
const loadedKeys = new Set<string>()

export const gitHogPullRequestDataFlowLogic = kea<gitHogPullRequestDataFlowLogicType>([
    props({} as GitHogPullRequestDataFlowLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((k) => ['scenes', 'githog', 'gitHogPullRequestDataFlowLogic', k]),
    actions({
        setView: (view: DataFlowView) => ({ view }),
        refreshDataFlow: true,
    }),
    reducers({
        view: [
            'diff' as DataFlowView,
            {
                setView: (_, { view }) => view,
            },
        ],
    }),
    loaders(({ props }) => ({
        dataFlow: [
            null as GitHogDataFlow | null,
            {
                loadDataFlow: async ({ refresh }: { refresh?: boolean } = {}) => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({
                        repository,
                        number: String(props.number),
                    })
                    if (refresh) {
                        params.set('refresh', 'true')
                    }
                    return await api.get<GitHogDataFlow>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_data_flow/?${params.toString()}`
                    )
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        refreshDataFlow: () => {
            actions.loadDataFlow({ refresh: true })
        },
    })),
    afterMount(({ actions, values, props }) => {
        // Guard against React StrictMode double-mount and back-to-back remounts (kea
        // tears down state on unmount, so module-level memoization is the only place
        // the prior-load fact survives an unmount/remount cycle).
        const key = `${props.owner}/${props.name}#${props.number}`
        if (values.dataFlow === null && !values.dataFlowLoading && !loadedKeys.has(key)) {
            loadedKeys.add(key)
            actions.loadDataFlow({})
        }
    }),
])
