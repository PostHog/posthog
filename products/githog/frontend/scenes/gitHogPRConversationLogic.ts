import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRConversationLogicType } from './gitHogPRConversationLogicType'

export interface GitHogPRConversationLogicProps {
    owner: string
    name: string
    number: number
}

export interface GitHogPRMessage {
    id: number
    body: string
    author_id: number | null
    author_name: string
    author_email: string
    is_mine: boolean
    edited_at: string | null
    created_at: string
}

interface MessageListResponse {
    repository: string
    pr_number: number
    messages: GitHogPRMessage[]
}

export const gitHogPRConversationLogic = kea<gitHogPRConversationLogicType>([
    props({} as GitHogPRConversationLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((k) => ['scenes', 'githog', 'gitHogPRConversationLogic', k]),
    actions({
        setComposerValue: (value: string) => ({ value }),
        submitComposer: true,
    }),
    reducers({
        composerValue: [
            '',
            {
                setComposerValue: (_, { value }) => value,
                postMessageSuccess: () => '',
            },
        ],
    }),
    loaders(({ props, values }) => ({
        messages: [
            [] as GitHogPRMessage[],
            {
                loadMessages: async () => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({ repository, number: String(props.number) })
                    const resp = await api.get<MessageListResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_messages/?${params.toString()}`
                    )
                    return resp.messages
                },
                postMessage: async ({ body }: { body: string }) => {
                    const created = await api.create<GitHogPRMessage>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_messages/`,
                        {
                            repository: `${props.owner}/${props.name}`,
                            number: props.number,
                            body,
                        }
                    )
                    return [...values.messages, created]
                },
                deleteMessage: async ({ id }: { id: number }) => {
                    await api.delete(`api/environments/${getCurrentTeamId()}/githog/pull_request_messages/${id}/`)
                    return values.messages.filter((m) => m.id !== id)
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        submitComposer: () => {
            const trimmed = values.composerValue.trim()
            if (!trimmed || values.messagesLoading) {
                return
            }
            actions.postMessage({ body: trimmed })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMessages()
    }),
])
