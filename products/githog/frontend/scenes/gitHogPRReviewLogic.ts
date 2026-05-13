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

export interface GitHogConversationMessage {
    id: number
    author_name: string
    author_email: string
    body: string
    created_at: string
}

export const gitHogPRReviewLogic = kea<gitHogPRReviewLogicType>([
    props({} as GitHogPRReviewLogicProps),
    key((props) => `${props.owner}/${props.name}#${props.number}`),
    path((key) => ['scenes', 'githog', 'gitHogPRReviewLogic', key]),

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
        messages: [
            [] as GitHogConversationMessage[],
            {
                loadMessages: async () => {
                    const repository = `${props.owner}/${props.name}`
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
        actions.loadMessages()
    }),
])
