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
    MindMapEdgeApi,
    MindMapPostItApi,
    MindmapEdgesListParams,
    MindmapPostitsListParams,
    PaginatedMindMapEdgeListApi,
    PaginatedMindMapPostItListApi,
    PatchedMindMapPostItApi,
    _BulkPositionRequestApi,
    _BulkPositionResponseApi,
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

export const getMindmapStateRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mindmap/state/`
}

export const mindmapStateRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMindmapStateRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMindmapEdgesListUrl = (projectId: string, params?: MindmapEdgesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mindmap_edges/?${stringifiedParams}`
        : `/api/projects/${projectId}/mindmap_edges/`
}

export const mindmapEdgesList = async (
    projectId: string,
    params?: MindmapEdgesListParams,
    options?: RequestInit
): Promise<PaginatedMindMapEdgeListApi> => {
    return apiMutator<PaginatedMindMapEdgeListApi>(getMindmapEdgesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMindmapEdgesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mindmap_edges/`
}

export const mindmapEdgesCreate = async (
    projectId: string,
    mindMapEdgeApi: NonReadonly<MindMapEdgeApi>,
    options?: RequestInit
): Promise<MindMapEdgeApi> => {
    return apiMutator<MindMapEdgeApi>(getMindmapEdgesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mindMapEdgeApi),
    })
}

export const getMindmapPostitsListUrl = (projectId: string, params?: MindmapPostitsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mindmap_postits/?${stringifiedParams}`
        : `/api/projects/${projectId}/mindmap_postits/`
}

export const mindmapPostitsList = async (
    projectId: string,
    params?: MindmapPostitsListParams,
    options?: RequestInit
): Promise<PaginatedMindMapPostItListApi> => {
    return apiMutator<PaginatedMindMapPostItListApi>(getMindmapPostitsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMindmapPostitsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/`
}

export const mindmapPostitsCreate = async (
    projectId: string,
    mindMapPostItApi: NonReadonly<MindMapPostItApi>,
    options?: RequestInit
): Promise<MindMapPostItApi> => {
    return apiMutator<MindMapPostItApi>(getMindmapPostitsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mindMapPostItApi),
    })
}

export const getMindmapPostitsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/${shortId}/`
}

export const mindmapPostitsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<MindMapPostItApi> => {
    return apiMutator<MindMapPostItApi>(getMindmapPostitsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getMindmapPostitsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/${shortId}/`
}

export const mindmapPostitsUpdate = async (
    projectId: string,
    shortId: string,
    mindMapPostItApi: NonReadonly<MindMapPostItApi>,
    options?: RequestInit
): Promise<MindMapPostItApi> => {
    return apiMutator<MindMapPostItApi>(getMindmapPostitsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mindMapPostItApi),
    })
}

export const getMindmapPostitsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/${shortId}/`
}

export const mindmapPostitsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedMindMapPostItApi?: NonReadonly<PatchedMindMapPostItApi>,
    options?: RequestInit
): Promise<MindMapPostItApi> => {
    return apiMutator<MindMapPostItApi>(getMindmapPostitsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMindMapPostItApi),
    })
}

export const getMindmapPostitsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/${shortId}/`
}

export const mindmapPostitsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMindmapPostitsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getMindmapPostitsBulkPositionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mindmap_postits/bulk_position/`
}

export const mindmapPostitsBulkPositionCreate = async (
    projectId: string,
    _bulkPositionRequestApi: _BulkPositionRequestApi,
    options?: RequestInit
): Promise<_BulkPositionResponseApi> => {
    return apiMutator<_BulkPositionResponseApi>(getMindmapPostitsBulkPositionCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_bulkPositionRequestApi),
    })
}
