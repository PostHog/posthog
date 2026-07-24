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
    ConfigListResponseApi,
    ConfigVersionApi,
    GrowthScoreLabConfigsRetrieveParams,
    IdentityMatchingLinksListParams,
    IdentityMatchingLinksResponseApi,
    IdentityMatchingRunsResponseApi,
    LabelListResponseApi,
    ProductPushCampaignActiveRetrieveParams,
    ProductPushCampaignApi,
    RunRequestApi,
    SaveRequestApi,
    SdkHealthReportApi,
    SdkHealthReportRetrieveParams,
} from './api.schemas'

export const getGrowthScoreLabActivateCreateUrl = () => {
    return `/api/growth_score_lab/activate/`
}

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabActivateCreate = async (
    activateRequestApi: ActivateRequestApi,
    options?: RequestInit
): Promise<ConfigVersionApi> => {
    return apiMutator<ConfigVersionApi>(getGrowthScoreLabActivateCreateUrl(), {
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

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabConfigsRetrieve = async (
    params: GrowthScoreLabConfigsRetrieveParams,
    options?: RequestInit
): Promise<ConfigListResponseApi> => {
    return apiMutator<ConfigListResponseApi>(getGrowthScoreLabConfigsRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getGrowthScoreLabLabelsRetrieveUrl = () => {
    return `/api/growth_score_lab/labels/`
}

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabLabelsRetrieve = async (options?: RequestInit): Promise<LabelListResponseApi> => {
    return apiMutator<LabelListResponseApi>(getGrowthScoreLabLabelsRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getGrowthScoreLabRunCreateUrl = () => {
    return `/api/growth_score_lab/run/`
}

/**
 * One JSON object per line: a verdict row ({company, domain, verdict, confidence, reasoning}) as each LLM call completes, then a final {summary: {classified, unknown, errors}} line. Persists nothing - spends real LLM money, so sample is capped at 100.
 * @summary Stream classifier verdicts for an unsaved draft config against recent archived orgs.
 */
export const growthScoreLabRunCreate = async (
    runRequestApi: RunRequestApi,
    options?: RequestInit
): Promise<Response> => {
    return apiMutator<Response>(getGrowthScoreLabRunCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson', ...options?.headers },
        body: JSON.stringify(runRequestApi),
    })
}

export const getGrowthScoreLabSaveCreateUrl = () => {
    return `/api/growth_score_lab/save/`
}

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabSaveCreate = async (
    saveRequestApi: SaveRequestApi,
    options?: RequestInit
): Promise<ConfigVersionApi> => {
    return apiMutator<ConfigVersionApi>(getGrowthScoreLabSaveCreateUrl(), {
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
