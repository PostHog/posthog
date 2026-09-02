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
    DataPointSubmitApi,
    DataPointSubmitResultApi,
    DiscussionCreateApi,
    DiscussionReplyApi,
    DiscussionReplyResultApi,
    DiscussionResolveApi,
    DiscussionThreadApi,
    DocApi,
    DocCollabSaveApi,
    DocCreateApi,
    DocPresenceApi,
    DocReorderApi,
    DocSummaryApi,
    DocsContextRetrieveParams,
    DocsHomeRetrieveParams,
    DocsListParams,
    DocsSearchRequestApi,
    DocsSearchResponseApi,
    PatchedDocUpdateApi,
    SpaceHomeApi,
    WatchActionApi,
    WatchBriefSubmitApi,
    WatchBriefSubmitResultApi,
    WatchVerdictSubmitApi,
} from './api.schemas'

export const getDocsListUrl = (projectId: string, params?: DocsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/docs/?${stringifiedParams}`
        : `/api/projects/${projectId}/docs/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsList = async (
    projectId: string,
    params?: DocsListParams,
    options?: RequestInit
): Promise<DocSummaryApi[]> => {
    return apiMutator<DocSummaryApi[]>(getDocsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDocsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/docs/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCreate = async (
    projectId: string,
    docCreateApi: DocCreateApi,
    options?: RequestInit
): Promise<DocApi> => {
    return apiMutator<DocApi>(getDocsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docCreateApi),
    })
}

export const getDocsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<DocApi> => {
    return apiMutator<DocApi>(getDocsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDocsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDocUpdateApi?: PatchedDocUpdateApi,
    options?: RequestInit
): Promise<DocApi> => {
    return apiMutator<DocApi>(getDocsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDocUpdateApi),
    })
}

export const getDocsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDocsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDocsCollabPresenceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/collab/presence/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCollabPresenceCreate = async (
    projectId: string,
    id: string,
    docPresenceApi: DocPresenceApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDocsCollabPresenceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docPresenceApi),
    })
}

export const getDocsCollabSaveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/collab/save/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCollabSaveCreate = async (
    projectId: string,
    id: string,
    docCollabSaveApi: DocCollabSaveApi,
    options?: RequestInit
): Promise<DocApi> => {
    return apiMutator<DocApi>(getDocsCollabSaveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docCollabSaveApi),
    })
}

export const getDocsCollabStreamRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/collab/stream/`
}

/**
 * SSE stream of accepted steps, carets, and discussion pings for this doc.
 */
export const docsCollabStreamRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getDocsCollabStreamRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDocsDiscussionsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/discussions/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DiscussionThreadApi[]> => {
    return apiMutator<DiscussionThreadApi[]>(getDocsDiscussionsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDocsDiscussionsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/docs/${id}/discussions/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsCreate = async (
    projectId: string,
    id: string,
    discussionCreateApi: DiscussionCreateApi,
    options?: RequestInit
): Promise<DiscussionReplyResultApi> => {
    return apiMutator<DiscussionReplyResultApi>(getDocsDiscussionsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(discussionCreateApi),
    })
}

export const getDocsDiscussionsReplyCreateUrl = (projectId: string, id: string, threadId: string) => {
    return `/api/projects/${projectId}/docs/${id}/discussions/${threadId}/reply/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsReplyCreate = async (
    projectId: string,
    id: string,
    threadId: string,
    discussionReplyApi: DiscussionReplyApi,
    options?: RequestInit
): Promise<DiscussionReplyResultApi> => {
    return apiMutator<DiscussionReplyResultApi>(getDocsDiscussionsReplyCreateUrl(projectId, id, threadId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(discussionReplyApi),
    })
}

export const getDocsDiscussionsResolveCreateUrl = (projectId: string, id: string, threadId: string) => {
    return `/api/projects/${projectId}/docs/${id}/discussions/${threadId}/resolve/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsResolveCreate = async (
    projectId: string,
    id: string,
    threadId: string,
    discussionResolveApi: DiscussionResolveApi,
    options?: RequestInit
): Promise<DiscussionThreadApi> => {
    return apiMutator<DiscussionThreadApi>(getDocsDiscussionsResolveCreateUrl(projectId, id, threadId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(discussionResolveApi),
    })
}

export const getDocsDiscussionsWatchCreateUrl = (projectId: string, id: string, threadId: string) => {
    return `/api/projects/${projectId}/docs/${id}/discussions/${threadId}/watch/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsWatchCreate = async (
    projectId: string,
    id: string,
    threadId: string,
    watchActionApi: WatchActionApi,
    options?: RequestInit
): Promise<DiscussionThreadApi> => {
    return apiMutator<DiscussionThreadApi>(getDocsDiscussionsWatchCreateUrl(projectId, id, threadId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(watchActionApi),
    })
}

export const getDocsContextRetrieveUrl = (projectId: string, params?: DocsContextRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/docs/context/?${stringifiedParams}`
        : `/api/projects/${projectId}/docs/context/`
}

/**
 * The space's context notes as a doc. Made on first use, from the wiki page when there is one.
 */
export const docsContextRetrieve = async (
    projectId: string,
    params?: DocsContextRetrieveParams,
    options?: RequestInit
): Promise<DocApi> => {
    return apiMutator<DocApi>(getDocsContextRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDocsDataPointsSubmitCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/docs/data_points/submit/`
}

/**
 * Called by the agent that a page asked for a data point. The query is checked and run once; on ok the page shows it live from then on. Submit again with the same request id to replace it.
 * @summary Submit the query behind a data point
 */
export const docsDataPointsSubmitCreate = async (
    projectId: string,
    dataPointSubmitApi: DataPointSubmitApi,
    options?: RequestInit
): Promise<DataPointSubmitResultApi> => {
    return apiMutator<DataPointSubmitResultApi>(getDocsDataPointsSubmitCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataPointSubmitApi),
    })
}

export const getDocsHomeRetrieveUrl = (projectId: string, params?: DocsHomeRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/docs/home/?${stringifiedParams}`
        : `/api/projects/${projectId}/docs/home/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsHomeRetrieve = async (
    projectId: string,
    params?: DocsHomeRetrieveParams,
    options?: RequestInit
): Promise<SpaceHomeApi> => {
    return apiMutator<SpaceHomeApi>(getDocsHomeRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDocsReorderCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/docs/reorder/`
}

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsReorderCreate = async (
    projectId: string,
    docReorderApi: DocReorderApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDocsReorderCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(docReorderApi),
    })
}

export const getDocsWatchesBriefCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/docs/watches/brief/`
}

/**
 * Called by the agent a page asked to watch a hypothesis. Each evidence query is run once; on ok the page rechecks them daily and a scout follows the signals. Submit again with the same request id to replace the brief.
 * @summary Submit the brief behind a watch
 */
export const docsWatchesBriefCreate = async (
    projectId: string,
    watchBriefSubmitApi: WatchBriefSubmitApi,
    options?: RequestInit
): Promise<WatchBriefSubmitResultApi> => {
    return apiMutator<WatchBriefSubmitResultApi>(getDocsWatchesBriefCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(watchBriefSubmitApi),
    })
}

export const getDocsWatchesVerdictCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/docs/watches/verdict/`
}

/**
 * Called by the agent that watches a hypothesis, after it looked at the data. Confirmed and refuted end the watch.
 * @summary Set the verdict on a watched hypothesis
 */
export const docsWatchesVerdictCreate = async (
    projectId: string,
    watchVerdictSubmitApi: WatchVerdictSubmitApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDocsWatchesVerdictCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(watchVerdictSubmitApi),
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
