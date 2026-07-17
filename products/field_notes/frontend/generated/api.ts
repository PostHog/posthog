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
import type { FieldNoteApi, FieldNotesListParams, PaginatedFieldNoteListApi, PatchedFieldNoteApi } from './api.schemas'

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

export const getFieldNotesListUrl = (projectId: string, params?: FieldNotesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/field_notes/?${stringifiedParams}`
        : `/api/projects/${projectId}/field_notes/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesList = async (
    projectId: string,
    params?: FieldNotesListParams,
    options?: RequestInit
): Promise<PaginatedFieldNoteListApi> => {
    return apiMutator<PaginatedFieldNoteListApi>(getFieldNotesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFieldNotesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/field_notes/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesCreate = async (
    projectId: string,
    fieldNoteApi: NonReadonly<FieldNoteApi>,
    options?: RequestInit
): Promise<FieldNoteApi> => {
    return apiMutator<FieldNoteApi>(getFieldNotesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fieldNoteApi),
    })
}

export const getFieldNotesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/field_notes/${id}/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FieldNoteApi> => {
    return apiMutator<FieldNoteApi>(getFieldNotesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFieldNotesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/field_notes/${id}/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesUpdate = async (
    projectId: string,
    id: string,
    fieldNoteApi: NonReadonly<FieldNoteApi>,
    options?: RequestInit
): Promise<FieldNoteApi> => {
    return apiMutator<FieldNoteApi>(getFieldNotesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fieldNoteApi),
    })
}

export const getFieldNotesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/field_notes/${id}/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFieldNoteApi?: NonReadonly<PatchedFieldNoteApi>,
    options?: RequestInit
): Promise<FieldNoteApi> => {
    return apiMutator<FieldNoteApi>(getFieldNotesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFieldNoteApi),
    })
}

export const getFieldNotesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/field_notes/${id}/`
}

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFieldNotesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
