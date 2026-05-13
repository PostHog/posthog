import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPullRequestDetailLogicType } from './gitHogPullRequestDetailLogicType'

export interface GitHogPullRequestDetailLogicProps {
    owner: string
    name: string
    number: number
}

export interface GitHogPullRequestDetail {
    number: number
    title: string
    body: string
    state: string
    draft: boolean
    html_url: string
    author: string
    author_avatar_url: string
    head_branch: string
    base_branch: string
    head_sha: string
    base_sha: string
    created_at: string
    updated_at: string
    merged_at: string | null
}

export const gitHogPullRequestDetailLogic = kea<gitHogPullRequestDetailLogicType>([
    props({} as GitHogPullRequestDetailLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((k) => ['scenes', 'githog', 'gitHogPullRequestDetailLogic', k]),
    loaders(({ props }) => ({
        pullRequest: [
            null as GitHogPullRequestDetail | null,
            {
                loadPullRequest: async () => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({ repository, number: String(props.number) })
                    return await api.get<GitHogPullRequestDetail>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request/?${params.toString()}`
                    )
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPullRequest()
    }),
])
