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
import type { LinkApi, LinksListParams, PaginatedLinkListApi, PatchedLinkApi } from './api.schemas'

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

export const getLinksListUrl = (projectId: string, params?: LinksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/links/?${stringifiedParams}`
        : `/api/projects/${projectId}/links/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksList = async (
    projectId: string,
    params?: LinksListParams,
    options?: RequestInit
): Promise<PaginatedLinkListApi> => {
    return apiMutator<PaginatedLinkListApi>(getLinksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLinksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/links/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksCreate = async (
    projectId: string,
    linkApi: NonReadonly<LinkApi>,
    options?: RequestInit
): Promise<LinkApi> => {
    return apiMutator<LinkApi>(getLinksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(linkApi),
    })
}

export const getLinksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/links/${id}/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<LinkApi> => {
    return apiMutator<LinkApi>(getLinksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLinksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/links/${id}/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksUpdate = async (
    projectId: string,
    id: string,
    linkApi: NonReadonly<LinkApi>,
    options?: RequestInit
): Promise<LinkApi> => {
    return apiMutator<LinkApi>(getLinksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(linkApi),
    })
}

export const getLinksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/links/${id}/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLinkApi?: NonReadonly<PatchedLinkApi>,
    options?: RequestInit
): Promise<LinkApi> => {
    return apiMutator<LinkApi>(getLinksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLinkApi),
    })
}

export const getLinksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/links/${id}/`
}

/**
 * Create, read, update, and delete links.
 */
export const linksDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLinksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
