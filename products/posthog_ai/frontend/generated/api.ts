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
    CoreMemoryListParams,
    DocsSearchRequestApi,
    DocsSearchResponseApi,
    HandsFreeTokenApi,
    MaxCoreMemoryApi,
    McpToolsCreate200,
    PaginatedMaxCoreMemoryListApi,
    PatchedMaxCoreMemoryApi,
    SynthesizeApi,
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

export const getCoreMemoryListUrl = (projectId: string, params?: CoreMemoryListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/core_memory/?${stringifiedParams}`
        : `/api/projects/${projectId}/core_memory/`
}

export const coreMemoryList = async (
    projectId: string,
    params?: CoreMemoryListParams,
    options?: RequestInit
): Promise<PaginatedMaxCoreMemoryListApi> => {
    return apiMutator<PaginatedMaxCoreMemoryListApi>(getCoreMemoryListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCoreMemoryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/core_memory/`
}

export const coreMemoryCreate = async (
    projectId: string,
    maxCoreMemoryApi: NonReadonly<MaxCoreMemoryApi>,
    options?: RequestInit
): Promise<MaxCoreMemoryApi> => {
    return apiMutator<MaxCoreMemoryApi>(getCoreMemoryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(maxCoreMemoryApi),
    })
}

export const getCoreMemoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/core_memory/${id}/`
}

export const coreMemoryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MaxCoreMemoryApi> => {
    return apiMutator<MaxCoreMemoryApi>(getCoreMemoryRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCoreMemoryUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/core_memory/${id}/`
}

export const coreMemoryUpdate = async (
    projectId: string,
    id: string,
    maxCoreMemoryApi: NonReadonly<MaxCoreMemoryApi>,
    options?: RequestInit
): Promise<MaxCoreMemoryApi> => {
    return apiMutator<MaxCoreMemoryApi>(getCoreMemoryUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(maxCoreMemoryApi),
    })
}

export const getCoreMemoryPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/core_memory/${id}/`
}

export const coreMemoryPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMaxCoreMemoryApi?: NonReadonly<PatchedMaxCoreMemoryApi>,
    options?: RequestInit
): Promise<MaxCoreMemoryApi> => {
    return apiMutator<MaxCoreMemoryApi>(getCoreMemoryPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMaxCoreMemoryApi),
    })
}

export const getMaxHandsFreeSynthesizeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/max_hands_free/synthesize/`
}

/**
 * Proxy text-to-speech to ElevenLabs, streaming mp3 audio back to the browser.
 *
 * The viewset has no per-action `parser_classes` other than this one because the
 * token endpoint takes no body. Putting JSONParser here keeps the rest of the
 * viewset parser-free.
 */
export const maxHandsFreeSynthesizeCreate = async (
    projectId: string,
    synthesizeApi: SynthesizeApi,
    options?: RequestInit
): Promise<Blob> => {
    return apiMutator<Blob>(getMaxHandsFreeSynthesizeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(synthesizeApi),
    })
}

export const getMaxHandsFreeTokenCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/max_hands_free/token/`
}

/**
 * Mint a single-use ElevenLabs Scribe realtime token.
 *
 * The browser uses the token to open a WebSocket directly to ElevenLabs — audio never
 * transits PostHog infrastructure. Tokens are time-bound (15 min) and single-use; the
 * per-team rate limit on this endpoint caps how often a user can mint new ones.
 *
 * Never logs the upstream response body — provider error responses can echo PII back and
 * we don't want any of that landing in structured logs.
 */
export const maxHandsFreeTokenCreate = async (projectId: string, options?: RequestInit): Promise<HandsFreeTokenApi> => {
    return apiMutator<HandsFreeTokenApi>(getMaxHandsFreeTokenCreateUrl(projectId), {
        ...options,
        method: 'POST',
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
