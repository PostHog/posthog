import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRLogicType } from './gitHogPRLogicType'

export interface GitHogPRLogicProps {
    owner: string
    name: string
    number: string
}

export interface GitHogPullRequestDetail {
    number: number
    title: string
    url: string
    state: string
    head_branch: string
    base_branch: string
    created_at: string
    updated_at: string
    author: string
    body: string
    draft: boolean
    merged: boolean
}

export const gitHogPRLogic = kea<gitHogPRLogicType>([
    props({} as GitHogPRLogicProps),
    key((props) => `${props.owner}/${props.name}#${props.number}`),
    path((prKey) => ['scenes', 'githog', 'gitHogPRLogic', prKey]),
    loaders(({ props }) => ({
        pullRequest: [
            null as GitHogPullRequestDetail | null,
            {
                loadPullRequest: async () => {
                    const repository = `${props.owner}/${props.name}`
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<{
                        repository: string
                        pull_request: GitHogPullRequestDetail
                    }>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request/?repository=${encodeURIComponent(
                            repository
                        )}&number=${encodeURIComponent(props.number)}`
                    )
                    return response.pull_request
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPullRequest()
    }),
])
