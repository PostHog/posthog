import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
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

export interface GitHogConversationMessage {
    id: number
    author_name: string
    author_email: string
    body: string
    created_at: string
}

export const gitHogPRReviewLogic = kea<gitHogPRReviewLogicType>([
    props({} as GitHogPRReviewLogicProps),
    key(({ owner, name, number }) => `${owner}/${name}#${number}`),
    path((prKey) => ['scenes', 'githog', 'gitHogPRReviewLogic', prKey]),

    actions({
        setDraftMessage: (text: string) => ({ text }),
        submitMessage: true,
        submitMessageSuccess: true,
        submitMessageFailure: true,
    }),

    reducers({
        draftMessage: [
            '' as string,
            {
                setDraftMessage: (_, { text }) => text,
                submitMessageSuccess: () => '',
            },
        ],
        submitting: [
            false as boolean,
            {
                submitMessage: () => true,
                submitMessageSuccess: () => false,
                submitMessageFailure: () => false,
            },
        ],
    }),

    loaders(({ props }) => ({
        prDetail: [
            null as GitHogPullRequestDetailResponse | null,
            {
                loadPRDetail: async () => {
                    const repository = `${props.owner}/${props.name}`
                    // nosemgrep: prefer-codegen-api
                    return await api.get<GitHogPullRequestDetailResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_diff/` +
                            `?repository=${encodeURIComponent(repository)}&number=${props.number}`
                    )
                },
            },
        ],
        messages: [
            [] as GitHogConversationMessage[],
            {
                loadMessages: async () => {
                    const repository = `${props.owner}/${props.name}`
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<{ messages: GitHogConversationMessage[] }>(
                        `api/environments/${getCurrentTeamId()}/githog/conversations/?repository=${encodeURIComponent(repository)}&number=${props.number}`
                    )
                    return response.messages
                },
            },
        ],
    })),

    listeners(({ props, values, actions }) => ({
        submitMessage: async () => {
            const body = values.draftMessage.trim()
            if (!body) {
                actions.submitMessageFailure()
                return
            }
            const repository = `${props.owner}/${props.name}`
            try {
                // nosemgrep: prefer-codegen-api
                await api.create(`api/environments/${getCurrentTeamId()}/githog/conversations/create/`, {
                    repository,
                    number: props.number,
                    body,
                })
                actions.submitMessageSuccess()
                actions.loadMessages()
            } catch {
                actions.submitMessageFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPRDetail()
        actions.loadMessages()
    }),
])
