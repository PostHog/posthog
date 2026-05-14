import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogRepoLogicType } from './gitHogRepoLogicType'

export interface GitHogRepoLogicProps {
    owner: string
    name: string
}

export interface GitHogPullRequest {
    number: number
    title: string
    url: string
    state: string
    head_branch: string
    base_branch: string
    created_at: string
    updated_at: string
    draft?: boolean
    author?: string
    author_avatar_url?: string
}

export const gitHogRepoLogic = kea<gitHogRepoLogicType>([
    props({} as GitHogRepoLogicProps),
    key((props) => `${props.owner}/${props.name}`),
    path((repoKey) => ['scenes', 'githog', 'gitHogRepoLogic', repoKey]),
    loaders(({ props }) => ({
        pullRequests: [
            [] as GitHogPullRequest[],
            {
                loadPullRequests: async () => {
                    const repository = `${props.owner}/${props.name}`
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<{ repository: string; pull_requests: GitHogPullRequest[] }>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_requests/?repository=${encodeURIComponent(
                            repository
                        )}&state=open`
                    )
                    return response.pull_requests
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPullRequests()
    }),
])
