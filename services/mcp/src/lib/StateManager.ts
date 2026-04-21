import type { ApiClient, GroupType } from '@/api/client'
import { getPostHogClient } from '@/lib/analytics'
import { ErrorCode, wrapError } from '@/lib/errors'
import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { sanitizeHeaderValue } from '@/lib/utils'
import type { ApiUser } from '@/schema/api'
import type { CachedOrg, CachedProject, CachedUser, State } from '@/tools/types'

import type { ScopedCache } from './cache/ScopedCache'

const CACHE_TTL_MS = 10 * 60 * 1000 // 10 minutes

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
            throw wrapError(`Failed to get user: ${userResult.error.message}`, userResult.error)
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

    private isCacheStale(fetchedAt: number | undefined): boolean {
        return !fetchedAt || Date.now() - fetchedAt > CACHE_TTL_MS
    }

    /**
     * Stale-while-cached helper. Returns fresh cached data if available; otherwise
     * fetches, writes both the value and its timestamp, and returns the fresh value.
     * On fetcher failure, returns the last-known cached value (possibly `undefined`)
     * and captures the exception.
     */
    private async getOrFetchCached<D extends keyof State, F extends keyof State>(opts: {
        name: string
        cacheKey: D
        fetchedAtKey: F
        fetcher: () => Promise<NonNullable<State[D]>>
    }): Promise<State[D]> {
        const [cached, fetchedAt] = (await Promise.all([
            this._cache.get(opts.cacheKey),
            this._cache.get(opts.fetchedAtKey),
        ])) as [State[D], number | undefined]

        if (cached !== undefined && !this.isCacheStale(fetchedAt)) {
            return cached
        }

        try {
            const data = await opts.fetcher()
            await Promise.all([
                this._cache.set(opts.cacheKey, data as State[D]),
                this._cache.set(opts.fetchedAtKey, Date.now() as State[F]),
            ])
            return data as State[D]
        } catch (error) {
            getPostHogClient().captureException(error, undefined, {
                tag: 'max_ai',
                context: `get_or_fetch_${opts.name}`,
            })
            return cached
        }
    }

    async getCachedOrFetchUser(): Promise<CachedUser | undefined> {
        const distinctId = await this.getDistinctId()
        return this.getOrFetchCached({
            name: 'user',
            cacheKey: `cachedUser:${distinctId}` as const,
            fetchedAtKey: `cachedUserFetchedAt:${distinctId}` as const,
            fetcher: () => this.getUser(),
        })
    }

    async getCachedOrFetchOrg(): Promise<CachedOrg | undefined> {
        const orgId = await this.getOrgID()
        if (!orgId) {
            return undefined
        }
        return this.getOrFetchCached({
            name: 'org',
            cacheKey: `cachedOrg:${orgId}` as const,
            fetchedAtKey: `cachedOrgFetchedAt:${orgId}` as const,
            fetcher: async () => {
                const result = await this._api.organizations().get({ orgId })
                if (!result.success) {
                    throw result.error
                }
                return result.data
            },
        })
    }

    async getCachedOrFetchProject(): Promise<CachedProject | undefined> {
        const projectId = await this.getProjectId()
        if (!projectId) {
            return undefined
        }
        return this.getOrFetchCached({
            name: 'project',
            cacheKey: `cachedProject:${projectId}` as const,
            fetchedAtKey: `cachedProjectFetchedAt:${projectId}` as const,
            fetcher: async () => {
                const result = await this._api.projects().get({ projectId })
                if (!result.success) {
                    throw result.error
                }
                return result.data
            },
        })
    }

    async getOrFetchGroupTypes(projectId: string): Promise<GroupType[] | undefined> {
        return this.getOrFetchCached({
            name: 'group_types',
            cacheKey: `groupTypes:${projectId}` as const,
            fetchedAtKey: `groupTypesFetchedAt:${projectId}` as const,
            fetcher: () => this._api.getGroupTypes(projectId),
        })
    }

    async getEnvironmentPrompt(): Promise<string | undefined> {
        const [user, org, project] = await Promise.all([
            this.getCachedOrFetchUser().catch(() => undefined),
            this.getCachedOrFetchOrg().catch(() => undefined),
            this.getCachedOrFetchProject().catch(() => undefined),
        ])
        return buildActiveEnvironmentContextPrompt(user, org, project)
    }

    /**
     * Resolve the workspace identifiers used to attach analytics events to the
     * `organization` and `project` PostHog groups. Reuses the cached user/org/project
     * entities, so repeat calls within a session are cheap.
     */
    async getAnalyticsContext(): Promise<{
        organizationId?: string
        projectId?: string
        projectUuid?: string
        projectName?: string
    }> {
        const [orgId, project] = await Promise.all([
            this._cache.get('orgId'),
            this.getCachedOrFetchProject().catch(() => undefined),
        ])

        return {
            ...(orgId ? { organizationId: orgId } : project?.organization ? { organizationId: project.organization } : {}),
            ...(project?.id !== undefined ? { projectId: String(project.id) } : {}),
            ...(project?.uuid ? { projectUuid: project.uuid } : {}),
            ...(project?.name ? { projectName: project.name } : {}),
        }
    }

    async getAiConsentGiven(): Promise<boolean | undefined> {
        try {
            const org = await this.getCachedOrFetchOrg()
            if (!org) {
                return undefined
            }
            const consent = (org as { is_ai_data_processing_approved?: boolean | null }).is_ai_data_processing_approved
            return !!consent
        } catch {
            return undefined
        }
    }
}
