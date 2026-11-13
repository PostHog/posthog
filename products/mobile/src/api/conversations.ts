import type {
    ConversationApi,
    ConversationMinimalApi,
    MessageApi,
    PaginatedConversationMinimalListApi,
} from '../../../../products/posthog_ai/frontend/generated/api.schemas'

import { apiJson, apiStream, projectPath } from './client'

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
