import type { ApiClient } from '@/api/client'
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

    private async _fetchUser() {
        const userResult = await this._api.users().me()
        if (!userResult.success) {
            throw new Error(`Failed to get user: ${userResult.error.message}`)
        }
        return userResult.data
    }

    async getUser() {
        if (!this._user) {
            this._user = await this._fetchUser()
        }

        return this._user
    }

    private async _fetchApiKey() {
        const apiKeyResult = await this._api.apiKeys().current()
        if (!apiKeyResult.success) {
            throw new Error(`Failed to get API key: ${apiKeyResult.error.message}`)
        }
        return apiKeyResult.data
    }

    async getApiKey() {
        let _apiKey = await this._cache.get('apiKey')

        if (!_apiKey) {
            _apiKey = await this._fetchApiKey()
            await this._cache.set('apiKey', _apiKey)
        }

        return _apiKey
    }

    async getDistinctId() {
        let _distinctId = await this._cache.get('distinctId')

        if (!_distinctId) {
            const user = await this.getUser()

            await this._cache.set('distinctId', user.distinct_id)
            _distinctId = user.distinct_id
        }

        return _distinctId
    }

    private async _getDefaultOrganizationAndProject(): Promise<{
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

        if (
            scoped_organizations.length === 0 ||
            scoped_organizations.includes(activeOrganization.id)
        ) {
            return { organizationId: activeOrganization.id, projectId: activeTeam.id }
        }

        const organizationId = scoped_organizations[0]!

        const projectsResult = await this._api
            .organizations()
            .projects({ orgId: organizationId })
            .list()

        if (!projectsResult.success) {
            throw projectsResult.error
        }

        if (projectsResult.data.length === 0) {
            throw new Error('API key does not have access to any projects')
        }

        const projectId = projectsResult.data[0]!

        return { organizationId, projectId: Number(projectId) }
    }

    async setDefaultOrganizationAndProject() {
        const { organizationId, projectId } = await this._getDefaultOrganizationAndProject()

        if (organizationId) {
            await this._cache.set('orgId', organizationId)
        }

        await this._cache.set('projectId', projectId.toString())

        return { organizationId, projectId }
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
            const { projectId } = await this.setDefaultOrganizationAndProject()
            return projectId.toString()
        }

        return projectId
    }
}
