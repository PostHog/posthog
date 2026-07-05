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
    BriefConfigApi,
    FeedbackVoteRequestApi,
    GenerateBriefRequestApi,
    OpportunityApi,
    PaginatedBriefConfigListApi,
    PaginatedOpportunityListApi,
    PaginatedProductBriefListListApi,
    PatchedBriefConfigApi,
    ProductBriefApi,
    PulseBriefConfigsListParams,
    PulseBriefsListParams,
    PulseOpportunitiesListParams,
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

export const getPulseBriefConfigsListUrl = (projectId: string, params?: PulseBriefConfigsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse/brief_configs/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse/brief_configs/`
}

export const pulseBriefConfigsList = async (
    projectId: string,
    params?: PulseBriefConfigsListParams,
    options?: RequestInit
): Promise<PaginatedBriefConfigListApi> => {
    return apiMutator<PaginatedBriefConfigListApi>(getPulseBriefConfigsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseBriefConfigsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse/brief_configs/`
}

export const pulseBriefConfigsCreate = async (
    projectId: string,
    briefConfigApi: NonReadonly<BriefConfigApi>,
    options?: RequestInit
): Promise<BriefConfigApi> => {
    return apiMutator<BriefConfigApi>(getPulseBriefConfigsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(briefConfigApi),
    })
}

export const getPulseBriefConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/brief_configs/${id}/`
}

export const pulseBriefConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BriefConfigApi> => {
    return apiMutator<BriefConfigApi>(getPulseBriefConfigsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseBriefConfigsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/brief_configs/${id}/`
}

export const pulseBriefConfigsUpdate = async (
    projectId: string,
    id: string,
    briefConfigApi: NonReadonly<BriefConfigApi>,
    options?: RequestInit
): Promise<BriefConfigApi> => {
    return apiMutator<BriefConfigApi>(getPulseBriefConfigsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(briefConfigApi),
    })
}

export const getPulseBriefConfigsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/brief_configs/${id}/`
}

export const pulseBriefConfigsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBriefConfigApi?: NonReadonly<PatchedBriefConfigApi>,
    options?: RequestInit
): Promise<BriefConfigApi> => {
    return apiMutator<BriefConfigApi>(getPulseBriefConfigsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBriefConfigApi),
    })
}

export const getPulseBriefConfigsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/brief_configs/${id}/`
}

export const pulseBriefConfigsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getPulseBriefConfigsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getPulseBriefsListUrl = (projectId: string, params?: PulseBriefsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse/briefs/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse/briefs/`
}

export const pulseBriefsList = async (
    projectId: string,
    params?: PulseBriefsListParams,
    options?: RequestInit
): Promise<PaginatedProductBriefListListApi> => {
    return apiMutator<PaginatedProductBriefListListApi>(getPulseBriefsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseBriefsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/briefs/${id}/`
}

export const pulseBriefsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProductBriefApi> => {
    return apiMutator<ProductBriefApi>(getPulseBriefsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseBriefsFeedbackCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/briefs/${id}/feedback/`
}

export const pulseBriefsFeedbackCreate = async (
    projectId: string,
    id: string,
    feedbackVoteRequestApi: FeedbackVoteRequestApi,
    options?: RequestInit
): Promise<ProductBriefApi> => {
    return apiMutator<ProductBriefApi>(getPulseBriefsFeedbackCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(feedbackVoteRequestApi),
    })
}

export const getPulseBriefsGenerateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/pulse/briefs/generate/`
}

export const pulseBriefsGenerateCreate = async (
    projectId: string,
    generateBriefRequestApi?: GenerateBriefRequestApi,
    options?: RequestInit
): Promise<ProductBriefApi> => {
    return apiMutator<ProductBriefApi>(getPulseBriefsGenerateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(generateBriefRequestApi),
    })
}

export const getPulseOpportunitiesListUrl = (projectId: string, params?: PulseOpportunitiesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/pulse/opportunities/?${stringifiedParams}`
        : `/api/projects/${projectId}/pulse/opportunities/`
}

export const pulseOpportunitiesList = async (
    projectId: string,
    params?: PulseOpportunitiesListParams,
    options?: RequestInit
): Promise<PaginatedOpportunityListApi> => {
    return apiMutator<PaginatedOpportunityListApi>(getPulseOpportunitiesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPulseOpportunitiesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/`
}

export const pulseOpportunitiesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPulseOpportunitiesActedCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/acted/`
}

export const pulseOpportunitiesActedCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesActedCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getPulseOpportunitiesDismissCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/dismiss/`
}

export const pulseOpportunitiesDismissCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesDismissCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getPulseOpportunitiesFeedbackCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/feedback/`
}

export const pulseOpportunitiesFeedbackCreate = async (
    projectId: string,
    id: string,
    feedbackVoteRequestApi: FeedbackVoteRequestApi,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesFeedbackCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(feedbackVoteRequestApi),
    })
}

export const getPulseOpportunitiesReopenCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/reopen/`
}

export const pulseOpportunitiesReopenCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesReopenCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getPulseOpportunitiesResearchCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/pulse/opportunities/${id}/research/`
}

export const pulseOpportunitiesResearchCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OpportunityApi> => {
    return apiMutator<OpportunityApi>(getPulseOpportunitiesResearchCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}
