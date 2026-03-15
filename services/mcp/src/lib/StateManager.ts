import type { ApiClient } from '@/api/client'
import { ErrorCode } from '@/lib/errors'
import { sanitizeHeaderValue } from '@/lib/utils'
import type { ApiUser } from '@/schema/api'
import type { State } from '@/tools/types'

import type { ScopedCache } from './cache/ScopedCache'

const AI_CONSENT_TTL_MS = 4 * 60 * 60 * 1000 // 4 hours

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
            throw new Error(ErrorCode.INVALID_API_KEY)
        }

        if (!introspectionResult.data.active) {
            throw new Error(ErrorCode.INACTIVE_OAUTH_TOKEN)
        }

        const { scope, scoped_teams, scoped_organizations, client_name } = introspectionResult.data

        const sanitizedClientName = sanitizeHeaderValue(client_name)
        if (sanitizedClientName) {
            await this._cache.set('clientName', sanitizedClientName)
        }

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

    async setDefaultOrganizationAndProject(): Promise<{
        organizationId: string | undefined
        projectId: number
    }> {
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

    async invalidateAiConsent(): Promise<void> {
        await this._cache.delete('aiConsentGiven')
        await this._cache.delete('aiConsentFetchedAt')
    }

    async getAiConsentGiven(): Promise<boolean | undefined> {
        const fetchedAt = await this._cache.get('aiConsentFetchedAt')
        const isExpired = !fetchedAt || Date.now() - fetchedAt > AI_CONSENT_TTL_MS
        if (!isExpired) {
            const cached = await this._cache.get('aiConsentGiven')
            if (cached !== undefined) {
                return cached
            }
        }

        try {
            const orgId = await this.getOrgID()
            if (!orgId) {
                return undefined
            }

            const orgResult = await this._api.organizations().get({ orgId })
            if (orgResult.success) {
                const org = orgResult.data as { is_ai_data_processing_approved?: boolean | null }
                const consent = !!org.is_ai_data_processing_approved
                await this._cache.set('aiConsentGiven', consent)
                await this._cache.set('aiConsentFetchedAt', Date.now())
                return consent
            }
        } catch {}

        return undefined
    }
}
