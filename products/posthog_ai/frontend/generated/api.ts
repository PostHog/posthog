import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    ConversationApi,
    ConversationsListParams,
    DocsSearchRequestApi,
    DocsSearchResponseApi,
    McpToolsCreate200,
    MessageApi,
    MessageMinimalApi,
    PaginatedConversationMinimalListApi,
    PatchedConversationApi,
    SandboxMessageResponseApi,
    SandboxOpenApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getConversationsListUrl = (projectId: string, params?: ConversationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/`
}

export const conversationsList = async (
    projectId: string,
    params?: ConversationsListParams,
    options?: RequestInit
): Promise<PaginatedConversationMinimalListApi> => {
    return apiMutator<PaginatedConversationMinimalListApi>(getConversationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/`
}

/**
 * Unified endpoint that handles both conversation creation and streaming.
 *
 * - If message is provided: Start new conversation processing
 * - If no message: Stream from existing conversation
 */
export const conversationsCreate = async (
    projectId: string,
    messageApi: MessageApi,
    options?: RequestInit
): Promise<MessageApi> => {
    return apiMutator<MessageApi>(getConversationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageApi),
    })
}

export const getConversationsRetrieveUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/`
}

export const conversationsRetrieve = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsRetrieveUrl(projectId, conversation), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsDestroyUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/`
}

/**
 * Delete a conversation.
 */
export const conversationsDestroy = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsDestroyUrl(projectId, conversation), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsAppendMessageCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/append_message/`
}

/**
 * Appends a message to an existing conversation without triggering AI processing.
 * This is used for client-side generated messages that need to be persisted
 * (e.g., support ticket confirmation messages).
 */
export const conversationsAppendMessageCreate = async (
    projectId: string,
    conversation: string,
    messageMinimalApi: MessageMinimalApi,
    options?: RequestInit
): Promise<MessageMinimalApi> => {
    return apiMutator<MessageMinimalApi>(getConversationsAppendMessageCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageMinimalApi),
    })
}

export const getConversationsCancelPartialUpdateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/cancel/`
}

/**
 * Cancel the conversation's in-progress LangGraph run.
 */
export const conversationsCancelPartialUpdate = async (
    projectId: string,
    conversation: string,
    patchedConversationApi?: NonReadonly<PatchedConversationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsCancelPartialUpdateUrl(projectId, conversation), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedConversationApi),
    })
}

export const getConversationsOpenCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/open/`
}

/**
 * Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the frontend opens SSE against. The conversation row is created on first use from the URL id.
 */
export const conversationsOpenCreate = async (
    projectId: string,
    conversation: string,
    sandboxOpenApi?: SandboxOpenApi,
    options?: RequestInit
): Promise<SandboxMessageResponseApi | void> => {
    return apiMutator<SandboxMessageResponseApi | void>(getConversationsOpenCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxOpenApi),
    })
}

export const getConversationsQueueRetrieveUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/`
}

export const conversationsQueueRetrieve = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueRetrieveUrl(projectId, conversation), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsQueueCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/`
}

export const conversationsQueueCreate = async (
    projectId: string,
    conversation: string,
    conversationApi?: NonReadonly<ConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(conversationApi),
    })
}

export const getConversationsQueuePartialUpdateUrl = (projectId: string, conversation: string, queueId: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/${queueId}/`
}

export const conversationsQueuePartialUpdate = async (
    projectId: string,
    conversation: string,
    queueId: string,
    patchedConversationApi?: NonReadonly<PatchedConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueuePartialUpdateUrl(projectId, conversation, queueId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedConversationApi),
    })
}

export const getConversationsQueueDestroyUrl = (projectId: string, conversation: string, queueId: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/${queueId}/`
}

export const conversationsQueueDestroy = async (
    projectId: string,
    conversation: string,
    queueId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsQueueDestroyUrl(projectId, conversation, queueId), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsQueueClearCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/clear/`
}

export const conversationsQueueClearCreate = async (
    projectId: string,
    conversation: string,
    conversationApi?: NonReadonly<ConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueClearCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(conversationApi),
    })
}

export const getMcpToolsCreateUrl = (projectId: string, toolName: string) => {
    return `/api/projects/${projectId}/mcp_tools/${toolName}/`
}

/**
 * Invoke an MCP tool by name.
 *
 * This endpoint allows MCP callers to invoke Max AI tools directly
 * without going through the full LangChain conversation flow.
 *
 * Scopes are resolved dynamically per tool via dangerously_get_required_scopes.
 */
export const mcpToolsCreate = async (
    projectId: string,
    toolName: string,
    options?: RequestInit
): Promise<McpToolsCreate200> => {
    return apiMutator<McpToolsCreate200>(getMcpToolsCreateUrl(projectId, toolName), {
        ...options,
        method: 'POST',
    })
}

export const getDocsSearchUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_tools/docs_search/`
}

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const docsSearch = async (
    projectId: string,
    docsSearchRequestApi: DocsSearchRequestApi,
    options?: RequestInit
): Promise<DocsSearchResponseApi> => {
    return apiMutator<DocsSearchResponseApi>(getDocsSearchUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docsSearchRequestApi),
    })
}
