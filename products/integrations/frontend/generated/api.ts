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
    DomainConnectApplyUrlRequestApi,
    DomainConnectApplyUrlResponseApi,
    DomainConnectCheckResponseApi,
    EmailDomainVerificationApi,
    GitHubAvailableInstallationsResponseApi,
    GitHubBranchesResponseApi,
    GitHubLinkExistingRequestApi,
    GitHubOAuthAuthorizeRequestApi,
    GitHubOAuthAuthorizeResponseApi,
    GitHubPrepareCallbackRequestApi,
    GitHubReposRefreshResponseApi,
    GitHubReposResponseApi,
    GitHubTeamsResponseApi,
    IntegrationAccessRequestApi,
    IntegrationAccessRequestResponseApi,
    IntegrationAssigneesResponseApi,
    IntegrationConfigApi,
    IntegrationsChannelsRetrieveParams,
    IntegrationsDomainConnectCheckRetrieveParams,
    IntegrationsGithubAssigneesRetrieveParams,
    IntegrationsGithubBranchesRetrieveParams,
    IntegrationsGithubReposRetrieveParams,
    IntegrationsGithubTeamsRetrieveParams,
    IntegrationsGitlabMembersRetrieveParams,
    IntegrationsJiraAssignableUsersRetrieveParams,
    IntegrationsLinearTeamMembersRetrieveParams,
    IntegrationsListParams,
    IntegrationsUsersRetrieveParams,
    JiraProjectsResponseApi,
    LinearTeamsResponseApi,
    OrganizationIntegrationApi,
    PaginatedIntegrationConfigListApi,
    PaginatedRoleExternalReferenceListApi,
    PatchedEmailSenderUpdateRequestApi,
    PatchedOrganizationIntegrationApi,
    PostHogConnectionForwardApi,
    PostHogConnectionForwardResponseApi,
    PostHogConnectionTargetApi,
    RoleExternalReferenceApi,
    RoleExternalReferencesListParams,
    RoleExternalReferencesLookupRetrieveParams,
    RoleLookupResponseApi,
    SlackChannelsResponseApi,
    SlackUsersResponseApi,
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

export const getIntegrationsEnvironmentMappingPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/integrations/${id}/environment-mapping/`
}

/**
 * ViewSet for organization-level integrations.
 *
 * Provides access to integrations that are scoped to the entire organization
 * (vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.
 *
 * Creation is handled by the integration installation flows
 * (e.g., Vercel marketplace installation). Users can disconnect integrations
 * via the DELETE endpoint.
 */
export const integrationsEnvironmentMappingPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedOrganizationIntegrationApi?: NonReadonly<PatchedOrganizationIntegrationApi>,
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

export const getRoleExternalReferencesListUrl = (organizationId: string, params?: RoleExternalReferencesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/role_external_references/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/role_external_references/`
}

export const roleExternalReferencesList = async (
    organizationId: string,
    params?: RoleExternalReferencesListParams,
    options?: RequestInit
): Promise<PaginatedRoleExternalReferenceListApi> => {
    return apiMutator<PaginatedRoleExternalReferenceListApi>(getRoleExternalReferencesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getRoleExternalReferencesCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/role_external_references/`
}

export const roleExternalReferencesCreate = async (
    organizationId: string,
    roleExternalReferenceApi: NonReadonly<RoleExternalReferenceApi>,
    options?: RequestInit
): Promise<RoleExternalReferenceApi> => {
    return apiMutator<RoleExternalReferenceApi>(getRoleExternalReferencesCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(roleExternalReferenceApi),
    })
}

export const getRoleExternalReferencesDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/role_external_references/${id}/`
}

export const roleExternalReferencesDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getRoleExternalReferencesDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getRoleExternalReferencesLookupRetrieveUrl = (
    organizationId: string,
    params: RoleExternalReferencesLookupRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/role_external_references/lookup/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/role_external_references/lookup/`
}

export const roleExternalReferencesLookupRetrieve = async (
    organizationId: string,
    params: RoleExternalReferencesLookupRetrieveParams,
    options?: RequestInit
): Promise<RoleLookupResponseApi> => {
    return apiMutator<RoleLookupResponseApi>(getRoleExternalReferencesLookupRetrieveUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsListUrl = (projectId: string, params?: IntegrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getIntegrationsAnthropicManagedAgentEnvsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/anthropic_managed_agent_environments/`
}

export const integrationsAnthropicManagedAgentEnvsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsAnthropicManagedAgentEnvsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsAnthropicManagedAgentVaultsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/anthropic_managed_agent_vaults/`
}

export const integrationsAnthropicManagedAgentVaultsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsAnthropicManagedAgentVaultsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsAnthropicManagedAgentsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/anthropic_managed_agents/`
}

export const integrationsAnthropicManagedAgentsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsAnthropicManagedAgentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsChannelsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: IntegrationsChannelsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/channels/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/channels/`
}

export const integrationsChannelsRetrieve = async (
    projectId: string,
    id: number,
    params?: IntegrationsChannelsRetrieveParams,
    options?: RequestInit
): Promise<SlackChannelsResponseApi> => {
    return apiMutator<SlackChannelsResponseApi>(getIntegrationsChannelsRetrieveUrl(projectId, id, params), {
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

/**
 * @summary Update an email sender
 */
export const integrationsEmailPartialUpdate = async (
    projectId: string,
    id: number,
    patchedEmailSenderUpdateRequestApi?: PatchedEmailSenderUpdateRequestApi,
    options?: RequestInit
): Promise<IntegrationConfigApi> => {
    return apiMutator<IntegrationConfigApi>(getIntegrationsEmailPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEmailSenderUpdateRequestApi),
    })
}

export const getIntegrationsEmailVerifyCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/verify/`
}

/**
 * Ask the email provider to check the sending domain's DNS records and return each record with its status. When every record is verified, all senders on the domain in this project become able to send.
 * @summary Verify an email sender's domain
 */
export const integrationsEmailVerifyCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<EmailDomainVerificationApi> => {
    return apiMutator<EmailDomainVerificationApi>(getIntegrationsEmailVerifyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getIntegrationsGithubAssigneesRetrieveUrl = (
    projectId: string,
    id: number,
    params: IntegrationsGithubAssigneesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/github_assignees/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/github_assignees/`
}

export const integrationsGithubAssigneesRetrieve = async (
    projectId: string,
    id: number,
    params: IntegrationsGithubAssigneesRetrieveParams,
    options?: RequestInit
): Promise<IntegrationAssigneesResponseApi> => {
    return apiMutator<IntegrationAssigneesResponseApi>(
        getIntegrationsGithubAssigneesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getIntegrationsGithubBranchesRetrieveUrl = (
    projectId: string,
    id: number,
    params: IntegrationsGithubBranchesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getIntegrationsGithubTeamsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: IntegrationsGithubTeamsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/github_teams/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/github_teams/`
}

export const integrationsGithubTeamsRetrieve = async (
    projectId: string,
    id: number,
    params?: IntegrationsGithubTeamsRetrieveParams,
    options?: RequestInit
): Promise<GitHubTeamsResponseApi> => {
    return apiMutator<GitHubTeamsResponseApi>(getIntegrationsGithubTeamsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGitlabMembersRetrieveUrl = (
    projectId: string,
    id: number,
    params?: IntegrationsGitlabMembersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/gitlab_members/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/gitlab_members/`
}

export const integrationsGitlabMembersRetrieve = async (
    projectId: string,
    id: number,
    params?: IntegrationsGitlabMembersRetrieveParams,
    options?: RequestInit
): Promise<IntegrationAssigneesResponseApi> => {
    return apiMutator<IntegrationAssigneesResponseApi>(getIntegrationsGitlabMembersRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
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

export const getIntegrationsJiraAssignableUsersRetrieveUrl = (
    projectId: string,
    id: number,
    params: IntegrationsJiraAssignableUsersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/jira_assignable_users/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/jira_assignable_users/`
}

export const integrationsJiraAssignableUsersRetrieve = async (
    projectId: string,
    id: number,
    params: IntegrationsJiraAssignableUsersRetrieveParams,
    options?: RequestInit
): Promise<IntegrationAssigneesResponseApi> => {
    return apiMutator<IntegrationAssigneesResponseApi>(
        getIntegrationsJiraAssignableUsersRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getIntegrationsJiraProjectsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/jira_projects/`
}

export const integrationsJiraProjectsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<JiraProjectsResponseApi> => {
    return apiMutator<JiraProjectsResponseApi>(getIntegrationsJiraProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinearTeamMembersRetrieveUrl = (
    projectId: string,
    id: number,
    params: IntegrationsLinearTeamMembersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/linear_team_members/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/linear_team_members/`
}

export const integrationsLinearTeamMembersRetrieve = async (
    projectId: string,
    id: number,
    params: IntegrationsLinearTeamMembersRetrieveParams,
    options?: RequestInit
): Promise<IntegrationAssigneesResponseApi> => {
    return apiMutator<IntegrationAssigneesResponseApi>(
        getIntegrationsLinearTeamMembersRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getIntegrationsLinearTeamsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linear_teams/`
}

export const integrationsLinearTeamsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<LinearTeamsResponseApi> => {
    return apiMutator<LinearTeamsResponseApi>(getIntegrationsLinearTeamsRetrieveUrl(projectId, id), {
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

export const getIntegrationsUsersRetrieveUrl = (
    projectId: string,
    id: number,
    params?: IntegrationsUsersRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/${id}/users/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/${id}/users/`
}

export const integrationsUsersRetrieve = async (
    projectId: string,
    id: number,
    params?: IntegrationsUsersRetrieveParams,
    options?: RequestInit
): Promise<SlackUsersResponseApi> => {
    return apiMutator<SlackUsersResponseApi>(getIntegrationsUsersRetrieveUrl(projectId, id, params), {
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

export const getIntegrationsDomainConnectApplyUrlCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/domain-connect/apply-url/`
}

/**
 * Build the signed URL that sends a person to their DNS host to approve the records for an email sending domain or a reverse proxy domain.
 * @summary Generate a Domain Connect apply URL
 */
export const integrationsDomainConnectApplyUrlCreate = async (
    projectId: string,
    domainConnectApplyUrlRequestApi: DomainConnectApplyUrlRequestApi,
    options?: RequestInit
): Promise<DomainConnectApplyUrlResponseApi> => {
    return apiMutator<DomainConnectApplyUrlResponseApi>(getIntegrationsDomainConnectApplyUrlCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(domainConnectApplyUrlRequestApi),
    })
}

export const getIntegrationsDomainConnectCheckRetrieveUrl = (
    projectId: string,
    params: IntegrationsDomainConnectCheckRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/domain-connect/check/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/domain-connect/check/`
}

/**
 * @summary Check Domain Connect support for a domain
 */
export const integrationsDomainConnectCheckRetrieve = async (
    projectId: string,
    params: IntegrationsDomainConnectCheckRetrieveParams,
    options?: RequestInit
): Promise<DomainConnectCheckResponseApi> => {
    return apiMutator<DomainConnectCheckResponseApi>(getIntegrationsDomainConnectCheckRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGithubAvailableInstallationsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/available_installations/`
}

/**
 * List GitHub installations this project can link.
 *
 * A GitHub App installs once per organization, so a second project links an existing
 * installation rather than reinstalling. This backs the picker: when more than one option
 * exists, the client passes the chosen installation_id to github/link_existing. The list also
 * includes installations the user's personal GitHub link can see but that aren't linked to any
 * project yet (``source_team_id: null``) — orphan installations approved on GitHub outside
 * PostHog's callback, which ``github/link_existing`` can adopt.
 */
export const integrationsGithubAvailableInstallationsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<GitHubAvailableInstallationsResponseApi> => {
    return apiMutator<GitHubAvailableInstallationsResponseApi>(
        getIntegrationsGithubAvailableInstallationsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getIntegrationsGithubLinkExistingCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/link_existing/`
}

/**
 * Reuse a GitHub installation already linked to a sibling team in the same organization.
 */
export const integrationsGithubLinkExistingCreate = async (
    projectId: string,
    gitHubLinkExistingRequestApi?: GitHubLinkExistingRequestApi,
    options?: RequestInit
): Promise<IntegrationConfigApi> => {
    return apiMutator<IntegrationConfigApi>(getIntegrationsGithubLinkExistingCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gitHubLinkExistingRequestApi),
    })
}

export const getIntegrationsGithubOauthAuthorizeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/oauth_authorize/`
}

/**
 * Mint a User OAuth URL to bootstrap a fresh `code` when the install flow returns without one.
 */
export const integrationsGithubOauthAuthorizeCreate = async (
    projectId: string,
    gitHubOAuthAuthorizeRequestApi?: GitHubOAuthAuthorizeRequestApi,
    options?: RequestInit
): Promise<GitHubOAuthAuthorizeResponseApi> => {
    return apiMutator<GitHubOAuthAuthorizeResponseApi>(getIntegrationsGithubOauthAuthorizeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gitHubOAuthAuthorizeRequestApi),
    })
}

export const getIntegrationsGithubPrepareCallbackCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/prepare_callback/`
}

/**
 * Seed GitHub setup callback state without redirecting to GitHub.
 *
 * Used when the user opens an existing installation's settings on github.com (e.g. PostHog
 * Code "Update in GitHub") so the subsequent Setup URL redirect can be validated.
 */
export const integrationsGithubPrepareCallbackCreate = async (
    projectId: string,
    gitHubPrepareCallbackRequestApi?: GitHubPrepareCallbackRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGithubPrepareCallbackCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gitHubPrepareCallbackRequestApi),
    })
}

export const getIntegrationsRequestAccessCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/request_access/`
}

/**
 * Notify project admins that a member is requesting an integration be connected.
 */
export const integrationsRequestAccessCreate = async (
    projectId: string,
    integrationAccessRequestApi: IntegrationAccessRequestApi,
    options?: RequestInit
): Promise<IntegrationAccessRequestResponseApi> => {
    return apiMutator<IntegrationAccessRequestResponseApi>(getIntegrationsRequestAccessCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationAccessRequestApi),
    })
}

export const getPosthogConnectionsForwardCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/posthog_connections/${id}/forward/`
}

/**
 * Replay an API request against the connected PostHog project. The server injects the connection's token; the response is passed through.
 * @summary Forward a request through a PostHog connection
 */
export const posthogConnectionsForwardCreate = async (
    projectId: string,
    id: string,
    postHogConnectionForwardApi: PostHogConnectionForwardApi,
    options?: RequestInit
): Promise<PostHogConnectionForwardResponseApi> => {
    return apiMutator<PostHogConnectionForwardResponseApi>(getPosthogConnectionsForwardCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(postHogConnectionForwardApi),
    })
}

export const getPosthogConnectionsTargetRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/posthog_connections/${id}/target/`
}

/**
 * Resolve which project, organization and region a PostHog connection points at, so callers can build target API paths without reading `api/users/@me/` through the connection first.
 * @summary Read the connected project's identity
 */
export const posthogConnectionsTargetRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PostHogConnectionTargetApi> => {
    return apiMutator<PostHogConnectionTargetApi>(getPosthogConnectionsTargetRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
