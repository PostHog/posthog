import type { ToolContext } from '@posthog/agent-shared'

import { projectPath } from './_posthog-api'

function ctx(over: Partial<ToolContext>): ToolContext {
    return {
        teamId: 1,
        applicationId: 'app',
        sessionId: 's',
        integrations: {},
        secret: () => undefined,
        log: () => {},
        posthogApiBaseUrl: 'http://localhost:8010',
        http: { fetch: async () => new Response() },
        ...over,
    } as unknown as ToolContext
}

describe('projectPath', () => {
    it('targets the caller posthog-user team, never the agent owning team', () => {
        // Agent owned by team 100; invoked by a PostHog user in team 200. The
        // data path must hit the caller's project so the API enforces the
        // caller's access — never the agent's team.
        const path = projectPath(ctx({ teamId: 100, posthogUserTeamId: 200 }), '/agent_applications/')
        expect(path).toBe('/api/projects/200/agent_applications/')
    })

    it('fails closed when there is no posthog-user context', () => {
        // No incoming PostHog principal → these tools must not silently fall
        // back to the agent's team (that would be ambient cross-tenant access).
        expect(() => projectPath(ctx({ teamId: 100, posthogUserTeamId: undefined }), '/x/')).toThrow(
            /posthog_user_context_required/
        )
    })
})
