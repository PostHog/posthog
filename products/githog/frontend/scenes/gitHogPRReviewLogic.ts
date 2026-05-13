import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRReviewLogicType } from './gitHogPRReviewLogicType'

export interface GitHogPRReviewLogicProps {
    owner: string
    name: string
    number: number
}

export interface GitHogPullRequestDetail {
    number: number
    title: string
    body: string
    url: string
    state: string
    draft: boolean
    head_branch: string
    head_sha: string
    base_branch: string
    base_sha: string
    author: string
    created_at: string
    updated_at: string
    additions: number
    deletions: number
    changed_files: number
    commits: number
}

export interface GitHogPullRequestFile {
    filename: string
    status: string
    additions: number
    deletions: number
    changes: number
    patch: string | null
}

export interface GitHogPullRequestDetailResponse {
    repository: string
    pull_request: GitHogPullRequestDetail
    files: GitHogPullRequestFile[]
    diff: string | null
}

export const gitHogPRReviewLogic = kea<gitHogPRReviewLogicType>([
    props({} as GitHogPRReviewLogicProps),
    key(({ owner, name, number }) => `${owner}/${name}#${number}`),
    path((prKey) => ['scenes', 'githog', 'gitHogPRReviewLogic', prKey]),
    loaders(({ props }) => ({
        prDetail: [
            null as GitHogPullRequestDetailResponse | null,
            {
                loadPRDetail: async () => {
                    const repository = `${props.owner}/${props.name}`
                    return await api.get<GitHogPullRequestDetailResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_diff/` +
                            `?repository=${encodeURIComponent(repository)}&number=${props.number}`
                    )
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPRDetail()
    }),
])
