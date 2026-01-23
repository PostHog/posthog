import type { ApiClient } from '@/api/client'
import { ErrorCode } from '@/lib/errors'
import type { ApiUser } from '@/schema/api'
import type { State } from '@/tools/types'

import type { ScopedCache } from './cache/ScopedCache'

export class StateManager {
    private _cache: ScopedCache<State>
    private _api: ApiClient
    private _user?: ApiUser

    constructor(cache: ScopedCache<State>, api: ApiClient) {
        this._cache = cache
        this._api = api
    }

    private async _fetchUser(): Promise<ApiUser> {
        const userResult = await this._api.users().me()
        if (!userResult.success) {
            throw new Error(`Failed to get user: ${userResult.error.message}`)
        }
        return userResult.data
    }

    async getUser(): Promise<ApiUser> {
        if (!this._user) {
            this._user = await this._fetchUser()
        }

        return this._user
    }

    private async _fetchApiKey(): Promise<NonNullable<State['apiKey']>> {
        const apiKeyResult = await this._api.apiKeys().current()
        if (apiKeyResult.success) {
            return apiKeyResult.data
        }

        const introspectionResult = await this._api.oauth().introspect({ token: this._api.config.apiToken })

        if (!introspectionResult.success) {
            throw new Error(`Failed to get API key: ${introspectionResult.error.message}`)
        }

        if (!introspectionResult.data.active) {
            throw new Error(ErrorCode.INACTIVE_OAUTH_TOKEN)
        }

        const { scope, scoped_teams, scoped_organizations } = introspectionResult.data

        return {
            scopes: scope ? scope.split(' ') : [],
            scoped_teams,
            scoped_organizations,
        }
    }

    async getApiKey(): Promise<NonNullable<State['apiKey']>> {
        let _apiKey = await this._cache.get('apiKey')

        if (!_apiKey) {
            _apiKey = await this._fetchApiKey()
            await this._cache.set('apiKey', _apiKey)
        }

        return _apiKey
    }

    async getDistinctId(): Promise<NonNullable<State['distinctId']>> {
        let _distinctId = await this._cache.get('distinctId')

        if (!_distinctId) {
            const user = await this.getUser()

            await this._cache.set('distinctId', user.distinct_id)
            _distinctId = user.distinct_id
        }

        return _distinctId
    }

    private async _getDefaultOrganizationAndProject(existingOrgId?: string): Promise<{
        organizationId?: string
        projectId: number
    }> {
        const { scoped_organizations, scoped_teams } = await this.getApiKey()
        const { organization: activeOrganization, team: activeTeam } = await this.getUser()

        if (scoped_teams.length > 0) {
            // Keys scoped to projects should only be scoped to one project
            if (scoped_teams.length > 1) {
                throw new Error(
                    'API key has access to multiple projects, please specify a single project ID or change the API key to have access to an organization to include the projects within it.'
                )
            }

            const projectId = scoped_teams[0]!

            return { projectId }
        }

        // If we have an existing org context, use it to fetch projects rather than
        // overwriting with the user's current default org. This prevents org context
        // from being reset when only projectId is missing.
        if (existingOrgId) {
            // Verify the org is accessible
            if (scoped_organizations.length > 0 && !scoped_organizations.includes(existingOrgId)) {
                throw new Error(`Organization ${existingOrgId} is not accessible with this API key`)
            }

            const projectsResult = await this._api.organizations().projects({ orgId: existingOrgId }).list()

            if (!projectsResult.success) {
                throw projectsResult.error
            }

            if (projectsResult.data.length === 0) {
                throw new Error(`No projects found in organization ${existingOrgId}`)
            }

            const projectId = projectsResult.data[0]!
            return { organizationId: existingOrgId, projectId: Number(projectId) }
        }

        if (scoped_organizations.length === 0 || scoped_organizations.includes(activeOrganization.id)) {
            return { organizationId: activeOrganization.id, projectId: activeTeam.id }
        }

        const organizationId = scoped_organizations[0]!

        const projectsResult = await this._api.organizations().projects({ orgId: organizationId }).list()

        if (!projectsResult.success) {
            throw projectsResult.error
        }

        if (projectsResult.data.length === 0) {
            throw new Error('API key does not have access to any projects')
        }

        const projectId = projectsResult.data[0]!

        return { organizationId, projectId: Number(projectId) }
    }

    async setDefaultOrganizationAndProject(preserveExistingOrg = false): Promise<{
        organizationId: string | undefined
        projectId: number
    }> {
        // Check for existing orgId if we need to preserve it
        const existingOrgId = preserveExistingOrg ? await this._cache.get('orgId') : undefined
        const { organizationId, projectId } = await this._getDefaultOrganizationAndProject(existingOrgId)

        // Only set orgId if we don't have an existing one we're preserving
        if (organizationId && !existingOrgId) {
            await this._cache.set('orgId', organizationId)
        }

        await this._cache.set('projectId', projectId.toString())

        return { organizationId: existingOrgId || organizationId, projectId }
    }

    async getOrgID(): Promise<string | undefined> {
        const orgId = await this._cache.get('orgId')

        if (!orgId) {
            const { organizationId } = await this.setDefaultOrganizationAndProject()

            return organizationId
        }

        return orgId
    }

    async getProjectId(): Promise<string> {
        const projectId = await this._cache.get('projectId')

        if (!projectId) {
            // Pass true to preserve existing org context - this prevents the org
            // from being reset to the user's default when only projectId is missing
            const { projectId } = await this.setDefaultOrganizationAndProject(true)
            return projectId.toString()
        }

        return projectId
    }
}
