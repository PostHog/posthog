/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    BatchImportApi,
    ManagedMigrationsListParams,
    PaginatedBatchImportListApi,
    PatchedBatchImportApi,
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

/**
 * List managed migrations using the response serializer
 */
export type managedMigrationsListResponse200 = {
    data: PaginatedBatchImportListApi
    status: 200
}

export type managedMigrationsListResponseSuccess = managedMigrationsListResponse200 & {
    headers: Headers
}
export type managedMigrationsListResponse = managedMigrationsListResponseSuccess

export const getManagedMigrationsListUrl = (projectId: string, params?: ManagedMigrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/managed_migrations/?${stringifiedParams}`
        : `/api/projects/${projectId}/managed_migrations/`
}

export const managedMigrationsList = async (
    projectId: string,
    params?: ManagedMigrationsListParams,
    options?: RequestInit
): Promise<managedMigrationsListResponse> => {
    return apiMutator<managedMigrationsListResponse>(getManagedMigrationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new managed migration/batch import.
 */
export type managedMigrationsCreateResponse201 = {
    data: void
    status: 201
}

export type managedMigrationsCreateResponseSuccess = managedMigrationsCreateResponse201 & {
    headers: Headers
}
export type managedMigrationsCreateResponse = managedMigrationsCreateResponseSuccess

export const getManagedMigrationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/managed_migrations/`
}

export const managedMigrationsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<managedMigrationsCreateResponse> => {
    return apiMutator<managedMigrationsCreateResponse>(getManagedMigrationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * Viewset for BatchImport model
 */
export type managedMigrationsRetrieveResponse200 = {
    data: BatchImportApi
    status: 200
}

export type managedMigrationsRetrieveResponseSuccess = managedMigrationsRetrieveResponse200 & {
    headers: Headers
}
export type managedMigrationsRetrieveResponse = managedMigrationsRetrieveResponseSuccess

export const getManagedMigrationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/`
}

export const managedMigrationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<managedMigrationsRetrieveResponse> => {
    return apiMutator<managedMigrationsRetrieveResponse>(getManagedMigrationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Viewset for BatchImport model
 */
export type managedMigrationsUpdateResponse200 = {
    data: BatchImportApi
    status: 200
}

export type managedMigrationsUpdateResponseSuccess = managedMigrationsUpdateResponse200 & {
    headers: Headers
}
export type managedMigrationsUpdateResponse = managedMigrationsUpdateResponseSuccess

export const getManagedMigrationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/`
}

export const managedMigrationsUpdate = async (
    projectId: string,
    id: string,
    batchImportApi: NonReadonly<BatchImportApi>,
    options?: RequestInit
): Promise<managedMigrationsUpdateResponse> => {
    return apiMutator<managedMigrationsUpdateResponse>(getManagedMigrationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchImportApi),
    })
}

/**
 * Viewset for BatchImport model
 */
export type managedMigrationsPartialUpdateResponse200 = {
    data: BatchImportApi
    status: 200
}

export type managedMigrationsPartialUpdateResponseSuccess = managedMigrationsPartialUpdateResponse200 & {
    headers: Headers
}
export type managedMigrationsPartialUpdateResponse = managedMigrationsPartialUpdateResponseSuccess

export const getManagedMigrationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/`
}

export const managedMigrationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchImportApi: NonReadonly<PatchedBatchImportApi>,
    options?: RequestInit
): Promise<managedMigrationsPartialUpdateResponse> => {
    return apiMutator<managedMigrationsPartialUpdateResponse>(getManagedMigrationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchImportApi),
    })
}

/**
 * Viewset for BatchImport model
 */
export type managedMigrationsDestroyResponse204 = {
    data: void
    status: 204
}

export type managedMigrationsDestroyResponseSuccess = managedMigrationsDestroyResponse204 & {
    headers: Headers
}
export type managedMigrationsDestroyResponse = managedMigrationsDestroyResponseSuccess

export const getManagedMigrationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/`
}

export const managedMigrationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<managedMigrationsDestroyResponse> => {
    return apiMutator<managedMigrationsDestroyResponse>(getManagedMigrationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Pause a running batch import.
 */
export type managedMigrationsPauseCreateResponse200 = {
    data: BatchImportApi
    status: 200
}

export type managedMigrationsPauseCreateResponseSuccess = managedMigrationsPauseCreateResponse200 & {
    headers: Headers
}
export type managedMigrationsPauseCreateResponse = managedMigrationsPauseCreateResponseSuccess

export const getManagedMigrationsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/pause/`
}

export const managedMigrationsPauseCreate = async (
    projectId: string,
    id: string,
    batchImportApi: NonReadonly<BatchImportApi>,
    options?: RequestInit
): Promise<managedMigrationsPauseCreateResponse> => {
    return apiMutator<managedMigrationsPauseCreateResponse>(getManagedMigrationsPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchImportApi),
    })
}

/**
 * Resume a paused batch import.
 */
export type managedMigrationsResumeCreateResponse200 = {
    data: BatchImportApi
    status: 200
}

export type managedMigrationsResumeCreateResponseSuccess = managedMigrationsResumeCreateResponse200 & {
    headers: Headers
}
export type managedMigrationsResumeCreateResponse = managedMigrationsResumeCreateResponseSuccess

export const getManagedMigrationsResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/managed_migrations/${id}/resume/`
}

export const managedMigrationsResumeCreate = async (
    projectId: string,
    id: string,
    batchImportApi: NonReadonly<BatchImportApi>,
    options?: RequestInit
): Promise<managedMigrationsResumeCreateResponse> => {
    return apiMutator<managedMigrationsResumeCreateResponse>(getManagedMigrationsResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchImportApi),
    })
}
