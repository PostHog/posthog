import type {
    ChatConfigurationApi,
    ConversationApi,
    ConversationMinimalApi,
    MessageApi,
    PaginatedConversationMinimalListApi,
} from '../../../../products/posthog_ai/frontend/generated/api.schemas'

import { ApiError, apiJson, apiStream, projectPath } from './client'

export async function getChatRuntime(signal?: AbortSignal): Promise<'langgraph' | 'sandbox'> {
    try {
        const configuration = await apiJson<ChatConfigurationApi>(projectPath('ai_chat_configuration/'), { signal })
        return configuration.sandbox === true ? 'sandbox' : 'langgraph'
    } catch (error) {
        // Servers predating the runtime endpoint can still serve classic conversations.
        if (error instanceof ApiError && error.status === 404) {
            return 'langgraph'
        }
        throw error
    }
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationMinimalApi[]> {
    const response = await apiJson<PaginatedConversationMinimalListApi>(projectPath('conversations/'), {
        query: { limit: 100 },
        signal,
    })
    return response.results
}

export function getConversation(id: string, signal?: AbortSignal): Promise<ConversationApi> {
    return apiJson<ConversationApi>(projectPath(`conversations/${encodeURIComponent(id)}/`), { signal })
}

export function streamConversation(body: MessageApi, signal?: AbortSignal): Promise<Response> {
    return apiStream(projectPath('conversations/'), { method: 'POST', json: body, signal })
}

export async function cancelConversation(id: string): Promise<void> {
    await apiJson(projectPath(`conversations/${encodeURIComponent(id)}/cancel/`), { method: 'PATCH' })
}
