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
    PaginatedProductTourListApi,
    PatchedProductTourSerializerCreateUpdateOnlyApi,
    ProductTourApi,
    ProductTourSerializerCreateUpdateOnlyApi,
    ProductToursListParams,
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

export const getProductToursListUrl = (projectId: string, params?: ProductToursListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/product_tours/?${stringifiedParams}`
        : `/api/projects/${projectId}/product_tours/`
}

export const productToursList = async (
    projectId: string,
    params?: ProductToursListParams,
    options?: RequestInit
): Promise<PaginatedProductTourListApi> => {
    return apiMutator<PaginatedProductTourListApi>(getProductToursListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getProductToursCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/product_tours/`
}

export const productToursCreate = async (
    projectId: string,
    productTourSerializerCreateUpdateOnlyApi: NonReadonly<ProductTourSerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<ProductTourSerializerCreateUpdateOnlyApi> => {
    return apiMutator<ProductTourSerializerCreateUpdateOnlyApi>(getProductToursCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(productTourSerializerCreateUpdateOnlyApi),
    })
}

export const getProductToursRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/product_tours/${id}/`
}

export const productToursRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProductTourApi> => {
    return apiMutator<ProductTourApi>(getProductToursRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getProductToursUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/product_tours/${id}/`
}

export const productToursUpdate = async (
    projectId: string,
    id: string,
    productTourApi: NonReadonly<ProductTourApi>,
    options?: RequestInit
): Promise<ProductTourApi> => {
    return apiMutator<ProductTourApi>(getProductToursUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(productTourApi),
    })
}

export const getProductToursPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/product_tours/${id}/`
}

export const productToursPartialUpdate = async (
    projectId: string,
    id: string,
    patchedProductTourSerializerCreateUpdateOnlyApi: NonReadonly<PatchedProductTourSerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<ProductTourSerializerCreateUpdateOnlyApi> => {
    return apiMutator<ProductTourSerializerCreateUpdateOnlyApi>(getProductToursPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProductTourSerializerCreateUpdateOnlyApi),
    })
}

export const getProductToursDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/product_tours/${id}/`
}

export const productToursDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getProductToursDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Generate tour step content using AI.
 */
export const getProductToursGenerateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/product_tours/generate/`
}

export const productToursGenerateCreate = async (
    projectId: string,
    productTourSerializerCreateUpdateOnlyApi: NonReadonly<ProductTourSerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<ProductTourSerializerCreateUpdateOnlyApi> => {
    return apiMutator<ProductTourSerializerCreateUpdateOnlyApi>(getProductToursGenerateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(productTourSerializerCreateUpdateOnlyApi),
    })
}
