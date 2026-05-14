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
import type { PaginatedSocialReferralListApi, SocialReferralApi, SocialReferralsListParams } from './api.schemas'

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

export const getSocialReferralsListUrl = (organizationId: string, params?: SocialReferralsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/social_referrals/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/social_referrals/`
}

/**
 * CRUD for referral share links under an organization.
 * @summary List social referrals
 */
export const socialReferralsList = async (
    organizationId: string,
    params?: SocialReferralsListParams,
    options?: RequestInit
): Promise<PaginatedSocialReferralListApi> => {
    return apiMutator<PaginatedSocialReferralListApi>(getSocialReferralsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSocialReferralsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/social_referrals/`
}

/**
 * CRUD for referral share links under an organization.
 * @summary Create social referral
 */
export const socialReferralsCreate = async (
    organizationId: string,
    socialReferralApi?: NonReadonly<SocialReferralApi>,
    options?: RequestInit
): Promise<SocialReferralApi> => {
    return apiMutator<SocialReferralApi>(getSocialReferralsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(socialReferralApi),
    })
}
