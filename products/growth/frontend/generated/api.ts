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
    ActivateRequestApi,
    GrowthScoreLabActivateCreateParams,
    GrowthScoreLabConfigsRetrieveParams,
    GrowthScoreLabLabelsRetrieveParams,
    GrowthScoreLabModelsRetrieveParams,
    GrowthScoreLabRunCreateParams,
    GrowthScoreLabSaveCreateParams,
    IdentityMatchingLinksListParams,
    IdentityMatchingLinksResponseApi,
    IdentityMatchingRunsResponseApi,
    ProductPushCampaignActiveRetrieveParams,
    ProductPushCampaignApi,
    RunRequestApi,
    SaveRequestApi,
    SdkHealthReportApi,
    SdkHealthReportRetrieveParams,
} from './api.schemas'

export const getGrowthScoreLabActivateCreateUrl = (params?: GrowthScoreLabActivateCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/activate/?${stringifiedParams}`
        : `/api/growth_score_lab/activate/`
}

export const growthScoreLabActivateCreate = async (
    activateRequestApi: ActivateRequestApi,
    params?: GrowthScoreLabActivateCreateParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabActivateCreateUrl(params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(activateRequestApi),
    })
}

export const getGrowthScoreLabConfigsRetrieveUrl = (params: GrowthScoreLabConfigsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/configs/?${stringifiedParams}`
        : `/api/growth_score_lab/configs/`
}

export const growthScoreLabConfigsRetrieve = async (
    params: GrowthScoreLabConfigsRetrieveParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabConfigsRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getGrowthScoreLabLabelsRetrieveUrl = (params?: GrowthScoreLabLabelsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/labels/?${stringifiedParams}`
        : `/api/growth_score_lab/labels/`
}

export const growthScoreLabLabelsRetrieve = async (
    params?: GrowthScoreLabLabelsRetrieveParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabLabelsRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getGrowthScoreLabModelsRetrieveUrl = (params?: GrowthScoreLabModelsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/models/?${stringifiedParams}`
        : `/api/growth_score_lab/models/`
}

export const growthScoreLabModelsRetrieve = async (
    params?: GrowthScoreLabModelsRetrieveParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabModelsRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getGrowthScoreLabRunCreateUrl = (params?: GrowthScoreLabRunCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/run/?${stringifiedParams}`
        : `/api/growth_score_lab/run/`
}

/**
 * One JSON object per line: a verdict row as each LLM call completes, then a final {summary: {classified, unknown, errors}} line. A legacy config (no output_fields) emits {company, domain, verdict, confidence, reasoning} rows; a configurable output schema (output_fields set) emits {company, domain, outputs: {<key>: value, ...}} rows instead. When input_query is set, rows are built from that HogQL query (capped at `sample`) instead of recently archived orgs. Persists nothing - spends real LLM money, so sample is capped at 100.
 * @summary Stream classifier verdicts for an unsaved draft config against recent archived orgs or a HogQL input query.
 */
export const growthScoreLabRunCreate = async (
    runRequestApi: RunRequestApi,
    params?: GrowthScoreLabRunCreateParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabRunCreateUrl(params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson', ...options?.headers },
        body: JSON.stringify(runRequestApi),
    })
}

export const getGrowthScoreLabSaveCreateUrl = (params?: GrowthScoreLabSaveCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/growth_score_lab/save/?${stringifiedParams}`
        : `/api/growth_score_lab/save/`
}

export const growthScoreLabSaveCreate = async (
    saveRequestApi: SaveRequestApi,
    params?: GrowthScoreLabSaveCreateParams,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabSaveCreateUrl(params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(saveRequestApi),
    })
}

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

export const getSdkHealthReportRetrieveUrl = (projectId: string, params?: SdkHealthReportRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/sdk_health/report/?${stringifiedParams}`
        : `/api/projects/${projectId}/sdk_health/report/`
}

/**
 * Returns a pre-digested health assessment of the PostHog SDKs the project is using. Covers which SDKs are current vs outdated (smart-semver rules with grace periods and traffic-percentage thresholds), per-version breakdown, and a human-readable reason for each assessment. Use this to diagnose SDK version issues, surface upgrade recommendations, or check overall SDK health.
 * @summary Get SDK health report for a project
 */
export const sdkHealthReportRetrieve = async (
    projectId: string,
    params?: SdkHealthReportRetrieveParams,
    options?: RequestInit
): Promise<SdkHealthReportApi> => {
    return apiMutator<SdkHealthReportApi>(getSdkHealthReportRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
