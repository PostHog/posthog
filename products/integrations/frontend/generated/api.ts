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
    PaginatedRoleExternalReferenceListApi,
    PaginatedUserGitHubIntegrationListResponseListApi,
    PatchedIntegrationConfigApi,
    PatchedOrganizationIntegrationApi,
    RoleExternalReferenceApi,
    RoleExternalReferencesListParams,
    RoleExternalReferencesLookupRetrieveParams,
    RoleLookupResponseApi,
    SlackChannelsResponseApi,
    UserGitHubLinkStartRequestApi,
    UserGitHubLinkStartResponseApi,
    UsersIntegrationsGithubReposRetrieveParams,
    UsersIntegrationsListParams,
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

export const getRoleExternalReferencesListUrl = (organizationId: string, params?: RoleExternalReferencesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
): Promise<SlackChannelsResponseApi> => {
    return apiMutator<SlackChannelsResponseApi>(getIntegrationsChannelsRetrieveUrl(projectId, id), {
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

/**
 * Clone a GitHub Integration row from another team in the same organization onto the current team.

GitHub's installation flow has no usable callback when the App is already installed on the
target org (the user lands on the Configure page and there is no automatic redirect back).
This endpoint lets users opt in to reusing an existing GitHub installation that's already
linked to a sibling team in the same PostHog organization, without going through GitHub.
 */
export const getIntegrationsGithubLinkExistingCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/link_existing/`
}

export const integrationsGithubLinkExistingCreate = async (
    projectId: string,
    integrationConfigApi: NonReadonly<IntegrationConfigApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGithubLinkExistingCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationConfigApi),
    })
}

/**
 * Mint a User OAuth round-trip URL for an existing GitHub App installation.

Used when GitHub redirects the install flow back without an OAuth `code`
(the App was already installed on the org and the user landed on the
Configure page). Without `code` we can't run `verify_user_installation_access`,
so the auto-link via link_existing only works when a sibling team in the
org has already captured the installation. For the orphan case — installation
exists on GitHub but no PostHog team has linked it yet — we send the user
through GitHub's User OAuth flow to mint a fresh `code`. State is bound
server-side to (user_id, team_id, installation_id) and is single-use.
The ``/complete/github-link/`` callback handles the return.
 */
export const getIntegrationsGithubOauthAuthorizeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/github/oauth_authorize/`
}

export const integrationsGithubOauthAuthorizeCreate = async (
    projectId: string,
    integrationConfigApi: NonReadonly<IntegrationConfigApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGithubOauthAuthorizeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationConfigApi),
    })
}

/**
 * `/api/users/@me/integrations/` — manage the user's personal GitHub integrations.
 * @summary List personal GitHub integrations
 */
export const getUsersIntegrationsListUrl = (uuid: string, params?: UsersIntegrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/integrations/?${stringifiedParams}`
        : `/api/users/${uuid}/integrations/`
}

export const usersIntegrationsList = async (
    uuid: string,
    params?: UsersIntegrationsListParams,
    options?: RequestInit
): Promise<PaginatedUserGitHubIntegrationListResponseListApi> => {
    return apiMutator<PaginatedUserGitHubIntegrationListResponseListApi>(getUsersIntegrationsListUrl(uuid, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Remove a specific GitHub installation by its installation_id.
 * @summary Disconnect a personal GitHub integration
 */
export const getUsersIntegrationsGithubDestroyUrl = (uuid: string, installationId: string) => {
    return `/api/users/${uuid}/integrations/github/${installationId}/`
}

export const usersIntegrationsGithubDestroy = async (
    uuid: string,
    installationId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersIntegrationsGithubDestroyUrl(uuid, installationId), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * List repositories accessible to a specific GitHub installation (paginated, cached).
 * @summary List repositories for a personal GitHub installation
 */
export const getUsersIntegrationsGithubReposRetrieveUrl = (
    uuid: string,
    installationId: string,
    params?: UsersIntegrationsGithubReposRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/integrations/github/${installationId}/repos/?${stringifiedParams}`
        : `/api/users/${uuid}/integrations/github/${installationId}/repos/`
}

export const usersIntegrationsGithubReposRetrieve = async (
    uuid: string,
    installationId: string,
    params?: UsersIntegrationsGithubReposRetrieveParams,
    options?: RequestInit
): Promise<GitHubReposResponseApi> => {
    return apiMutator<GitHubReposResponseApi>(
        getUsersIntegrationsGithubReposRetrieveUrl(uuid, installationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Start GitHub linking: either full App install or OAuth-only (user-to-server).

``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
under projects).

Usually returns ``install_url`` pointing at ``/installations/new`` so the
user can pick any GitHub org (new or already connected).  GitHub's install
page handles both cases: orgs where the app is installed show "Configure"
(no admin needed), orgs where it isn't show "Install" (needs admin).

**PostHog Code fast path:** when ``connect_from`` is ``"posthog_code"``,
the current project already has a team-level GitHub installation, and the
user has no ``UserIntegration`` for that installation yet, we skip the org
picker and redirect straight to ``/login/oauth/authorize`` so the user
only authorizes themselves and returns to PostHog Code immediately.

In both cases the response key is ``install_url`` for compatibility with callers.
 * @summary Start GitHub personal integration linking
 */
export const getUsersIntegrationsGithubStartCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/integrations/github/start/`
}

export const usersIntegrationsGithubStartCreate = async (
    uuid: string,
    userGitHubLinkStartRequestApi: UserGitHubLinkStartRequestApi,
    options?: RequestInit
): Promise<UserGitHubLinkStartResponseApi> => {
    return apiMutator<UserGitHubLinkStartResponseApi>(getUsersIntegrationsGithubStartCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userGitHubLinkStartRequestApi),
    })
}
