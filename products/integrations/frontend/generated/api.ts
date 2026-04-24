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
    GitHubBranchesResponseApi,
    GitHubReposRefreshResponseApi,
    GitHubReposResponseApi,
    IntegrationConfigApi,
    IntegrationsGithubBranchesRetrieveParams,
    IntegrationsGithubReposRetrieveParams,
    IntegrationsListParams,
    OrganizationIntegrationApi,
    PaginatedIntegrationConfigListApi,
    PatchedIntegrationConfigApi,
    PatchedOrganizationIntegrationApi,
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
 * ViewSet for organization-level integrations.

Provides access to integrations that are scoped to the entire organization
(vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

Creation is handled by the integration installation flows
(e.g., Vercel marketplace installation). Users can disconnect integrations
via the DELETE endpoint.
 */
export const getIntegrationsEnvironmentMappingPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/integrations/${id}/environment-mapping/`
}

export const integrationsEnvironmentMappingPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedOrganizationIntegrationApi: NonReadonly<PatchedOrganizationIntegrationApi>,
    options?: RequestInit
): Promise<OrganizationIntegrationApi> => {
    return apiMutator<OrganizationIntegrationApi>(
        getIntegrationsEnvironmentMappingPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedOrganizationIntegrationApi),
        }
    )
}

export const getIntegrationsListUrl = (projectId: string, params?: IntegrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/`
}

export const integrationsList = async (
    projectId: string,
    params?: IntegrationsListParams,
    options?: RequestInit
): Promise<PaginatedIntegrationConfigListApi> => {
    return apiMutator<PaginatedIntegrationConfigListApi>(getIntegrationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/`
}

export const integrationsCreate = async (
    projectId: string,
    integrationConfigApi: NonReadonly<IntegrationConfigApi>,
    options?: RequestInit
): Promise<IntegrationConfigApi> => {
    return apiMutator<IntegrationConfigApi>(getIntegrationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationConfigApi),
    })
}

export const getIntegrationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<IntegrationConfigApi> => {
    return apiMutator<IntegrationConfigApi>(getIntegrationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getIntegrationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getIntegrationsChannelsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/channels/`
}

export const integrationsChannelsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupListsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_lists/`
}

export const integrationsClickupListsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupListsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupSpacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_spaces/`
}

export const integrationsClickupSpacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupSpacesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupWorkspacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_workspaces/`
}

export const integrationsClickupWorkspacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupWorkspacesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsEmailPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/`
}

export const integrationsEmailPartialUpdate = async (
    projectId: string,
    id: number,
    patchedIntegrationConfigApi: NonReadonly<PatchedIntegrationConfigApi>,
    options?: RequestInit
): Promise<IntegrationConfigApi> => {
    return apiMutator<IntegrationConfigApi>(getIntegrationsEmailPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedIntegrationConfigApi),
    })
}

export const getIntegrationsEmailVerifyCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/verify/`
}

export const integrationsEmailVerifyCreate = async (
    projectId: string,
    id: number,
    integrationConfigApi: NonReadonly<IntegrationConfigApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsEmailVerifyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationConfigApi),
    })
}

export const getIntegrationsGithubBranchesRetrieveUrl = (
    projectId: string,
    id: number,
    params: IntegrationsGithubBranchesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/github_branches/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/github_branches/`
}

export const integrationsGithubBranchesRetrieve = async (
    projectId: string,
    id: number,
    params: IntegrationsGithubBranchesRetrieveParams,
    options?: RequestInit
): Promise<GitHubBranchesResponseApi> => {
    return apiMutator<GitHubBranchesResponseApi>(getIntegrationsGithubBranchesRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGithubReposRetrieveUrl = (
    projectId: string,
    id: number,
    params?: IntegrationsGithubReposRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/github_repos/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/github_repos/`
}

export const integrationsGithubReposRetrieve = async (
    projectId: string,
    id: number,
    params?: IntegrationsGithubReposRetrieveParams,
    options?: RequestInit
): Promise<GitHubReposResponseApi> => {
    return apiMutator<GitHubReposResponseApi>(getIntegrationsGithubReposRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGithubReposRefreshCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/github_repos/refresh/`
}

export const integrationsGithubReposRefreshCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<GitHubReposRefreshResponseApi> => {
    return apiMutator<GitHubReposRefreshResponseApi>(getIntegrationsGithubReposRefreshCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getIntegrationsGoogleAccessibleAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_accessible_accounts/`
}

export const integrationsGoogleAccessibleAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGoogleAccessibleAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGoogleConversionActionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_conversion_actions/`
}

export const integrationsGoogleConversionActionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGoogleConversionActionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsJiraProjectsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/jira_projects/`
}

export const integrationsJiraProjectsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsJiraProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinearTeamsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linear_teams/`
}

export const integrationsLinearTeamsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinearTeamsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const integrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const integrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsTwilioPhoneNumbersRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/twilio_phone_numbers/`
}

export const integrationsTwilioPhoneNumbersRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsTwilioPhoneNumbersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsAuthorizeRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/authorize/`
}

export const integrationsAuthorizeRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getIntegrationsAuthorizeRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Unified endpoint for generating Domain Connect apply URLs.

Accepts a context ("email" or "proxy") and the relevant resource ID.
The backend resolves the domain, template variables, and service ID
based on context, then builds the signed apply URL.
 */
export const getIntegrationsDomainConnectApplyUrlCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/domain-connect/apply-url/`
}

export const integrationsDomainConnectApplyUrlCreate = async (
    projectId: string,
    integrationConfigApi: NonReadonly<IntegrationConfigApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsDomainConnectApplyUrlCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationConfigApi),
    })
}

export const getIntegrationsDomainConnectCheckRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/domain-connect/check/`
}

export const integrationsDomainConnectCheckRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsDomainConnectCheckRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
