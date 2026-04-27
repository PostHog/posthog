import type { HttpClient } from './http-client'

interface UserMeResponse {
    team?: { id: number }
    organization?: { id: string }
}

/**
 * Resolves the active project and organization from `/api/users/@me/`. Fetched once,
 * lazily, and cached for the lifetime of the server. The agent can override per-call by
 * providing `input.path.project_id` / `input.path.organization_id` explicitly.
 */
export class Context {
    private projectIdPromise?: Promise<string>
    private organizationIdPromise?: Promise<string>
    private mePromise?: Promise<UserMeResponse>

    constructor(private http: HttpClient) {}

    async getProjectId(): Promise<string> {
        if (!this.projectIdPromise) {
            this.projectIdPromise = this.fetchMe().then((me) => {
                if (me.team?.id === undefined) {
                    throw new Error(
                        'Could not resolve a default project: /api/users/@me/ did not return a team. Pass input.path.project_id explicitly.'
                    )
                }
                return String(me.team.id)
            })
        }
        return this.projectIdPromise
    }

    async getEnvironmentId(): Promise<string> {
        // PostHog environments and projects share the same id at the API layer.
        return this.getProjectId()
    }

    async getOrganizationId(): Promise<string> {
        if (!this.organizationIdPromise) {
            this.organizationIdPromise = this.fetchMe().then((me) => {
                if (!me.organization?.id) {
                    throw new Error(
                        'Could not resolve a default organization: /api/users/@me/ did not return an organization. Pass input.path.organization_id explicitly.'
                    )
                }
                return me.organization.id
            })
        }
        return this.organizationIdPromise
    }

    private fetchMe(): Promise<UserMeResponse> {
        if (!this.mePromise) {
            this.mePromise = this.http.request<UserMeResponse>({
                method: 'GET',
                path: '/api/users/@me/',
            })
        }
        return this.mePromise
    }
}
