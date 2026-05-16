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
    afterMount(({ actions }) => {
        // Always ask the backend — its single-flight lock + DB cache make
        // re-mounts cheap. The previous module-level "loadedKeys" guard
        // tried to dedupe StrictMode double-mounts but also blocked the
        // PR-revisit path: kea tears down `dataFlow` on unmount, so on the
        // next mount we'd see `null` AND the guard would skip loading,
        // leaving the UI permanently "not available" until manual refresh.
        actions.loadDataFlow({})
    }),
])
