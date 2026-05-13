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
    title: string
    file: string
    detail: string
}

export interface GitHogDataFlow {
    repository: string
    pr_number: number
    head_sha: string
    base_sha: string
    mermaid_before: string
    mermaid_after: string
    steps_before: GitHogDataFlowStep[]
    steps_after: GitHogDataFlowStep[]
    summary: string
    truncated: boolean
    cached: boolean
    computed_at: string
}

export type DataFlowView = 'mermaid' | 'steps'

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
            'mermaid' as DataFlowView,
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
        actions.loadDataFlow({})
    }),
])
