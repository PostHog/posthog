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
    PaginatedToolbarAnnotationListApi,
    PatchedToolbarAnnotationApi,
    ToolbarAnnotationApi,
    ToolbarAnnotationsListParams,
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

export const getToolbarAnnotationsListUrl = (projectId: string, params?: ToolbarAnnotationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/toolbar_annotations/?${stringifiedParams}`
        : `/api/projects/${projectId}/toolbar_annotations/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsList = async (
    projectId: string,
    params?: ToolbarAnnotationsListParams,
    options?: RequestInit
): Promise<PaginatedToolbarAnnotationListApi> => {
    return apiMutator<PaginatedToolbarAnnotationListApi>(getToolbarAnnotationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getToolbarAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/toolbar_annotations/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsCreate = async (
    projectId: string,
    toolbarAnnotationApi: NonReadonly<ToolbarAnnotationApi>,
    options?: RequestInit
): Promise<ToolbarAnnotationApi> => {
    return apiMutator<ToolbarAnnotationApi>(getToolbarAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(toolbarAnnotationApi),
    })
}

export const getToolbarAnnotationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/toolbar_annotations/${id}/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ToolbarAnnotationApi> => {
    return apiMutator<ToolbarAnnotationApi>(getToolbarAnnotationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getToolbarAnnotationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/toolbar_annotations/${id}/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsUpdate = async (
    projectId: string,
    id: string,
    toolbarAnnotationApi: NonReadonly<ToolbarAnnotationApi>,
    options?: RequestInit
): Promise<ToolbarAnnotationApi> => {
    return apiMutator<ToolbarAnnotationApi>(getToolbarAnnotationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(toolbarAnnotationApi),
    })
}

export const getToolbarAnnotationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/toolbar_annotations/${id}/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedToolbarAnnotationApi?: NonReadonly<PatchedToolbarAnnotationApi>,
    options?: RequestInit
): Promise<ToolbarAnnotationApi> => {
    return apiMutator<ToolbarAnnotationApi>(getToolbarAnnotationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedToolbarAnnotationApi),
    })
}

export const getToolbarAnnotationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/toolbar_annotations/${id}/`
}

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getToolbarAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
