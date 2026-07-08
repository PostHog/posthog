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
    IdentityMatchingLinksListParams,
    IdentityMatchingLinksResponseApi,
    IdentityMatchingRunsResponseApi,
    ProductPushCampaignActiveRetrieveParams,
    ProductPushCampaignApi,
} from './api.schemas'

export const getProductPushCampaignActiveRetrieveUrl = (
    organizationId: string,
    params?: ProductPushCampaignActiveRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/product_push_campaign/active/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/product_push_campaign/active/`
}

/**
 * The organization's currently active product push campaign. 204 when no campaign is active, or when the given project already uses the campaign's product.
 */
export const productPushCampaignActiveRetrieve = async (
    organizationId: string,
    params?: ProductPushCampaignActiveRetrieveParams,
    options?: RequestInit
): Promise<ProductPushCampaignApi | void> => {
    return apiMutator<ProductPushCampaignApi | void>(getProductPushCampaignActiveRetrieveUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIdentityMatchingLinksListUrl = (projectId: string, params?: IdentityMatchingLinksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/identity_matching_links/?${stringifiedParams}`
        : `/api/projects/${projectId}/identity_matching_links/`
}

/**
 * Scored links between anonymous distinct IDs and identified persons, with the evidence behind each link. Produced by the identity matching Dagster job; empty until that job has run for this project.
 * @summary List identity matching links
 */
export const identityMatchingLinksList = async (
    projectId: string,
    params?: IdentityMatchingLinksListParams,
    options?: RequestInit
): Promise<IdentityMatchingLinksResponseApi> => {
    return apiMutator<IdentityMatchingLinksResponseApi>(getIdentityMatchingLinksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIdentityMatchingLinksRunsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/identity_matching_links/runs/`
}

/**
 * Recent identity matching runs for this project with link counts, tier breakdowns, and paid attribution stats per scoring model, most recent first.
 * @summary List identity matching runs
 */
export const identityMatchingLinksRunsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<IdentityMatchingRunsResponseApi> => {
    return apiMutator<IdentityMatchingRunsResponseApi>(getIdentityMatchingLinksRunsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
