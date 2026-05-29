/**
 * Unit tests for the Slack → PostHog user bridge. The Slack and Postgres
 * calls are stubbed; the contract under test is "what does the bridge
 * cache on the AgentUser row given each possible upstream response."
 */

import { AgentUser, MemoryIdentityStore, MemoryIntegrationStore } from '@posthog/agent-shared'

import { bridgeSlackToPosthogUser } from './slack-posthog-bridge'

function makeAgentUser(overrides: Partial<AgentUser> = {}): AgentUser {
    return {
        id: 'au-bob',
        team_id: 1,
        application_id: 'app',
        principal_kind: 'slack',
        principal_id: 'T01ACME:U-BOB',
        metadata: { workspace: 'T01ACME', slack_user: 'U-BOB' },
        posthog_user_id: undefined,
        created_at: '2026-05-27T00:00:00Z',
        ...overrides,
    }
}

function fakePosthogDb(emailToUserId: Record<string, number>): import('pg').Pool {
    return {
        // The bridge only calls `.query(sql, params)` and reads `rowCount` +
        // `rows`. A stub matching that minimal surface is enough.
        async query(_sql: string, params: unknown[]) {
            const email = String(params[0] ?? '').toLowerCase()
            const id = Object.entries(emailToUserId).find(([k]) => k.toLowerCase() === email)?.[1]
            if (id === undefined) {
                return { rowCount: 0, rows: [] }
            }
            return { rowCount: 1, rows: [{ id }] }
        },
    } as unknown as import('pg').Pool
}

describe('bridgeSlackToPosthogUser', () => {
    it('caches the matched posthog_user.id when slack returns an email that exists', async () => {
        const integrations = new MemoryIntegrationStore()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser()
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => 'bob@posthog.com',
        })

        expect(userId).toBe(42)
        const cached = await identities.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBe(42)
    })

    it('caches `null` when slack returns an email with no matching posthog_user', async () => {
        const integrations = new MemoryIntegrationStore()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ id: 'au-external' })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-EXTERNAL', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => 'external@example.com',
        })

        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBeNull()
    })

    it('returns the cached posthog_user_id without re-running the lookup', async () => {
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ posthog_user_id: 7 })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        let calls = 0
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: new MemoryIntegrationStore(),
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => {
                calls++
                return 'unused@posthog.com'
            },
        })
        expect(userId).toBe(7)
        expect(calls).toBe(0)
    })

    it('respects an explicit cached null (no match found previously) without re-asking slack', async () => {
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ posthog_user_id: null })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        let calls = 0
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: new MemoryIntegrationStore(),
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => {
                calls++
                return 'unused@posthog.com'
            },
        })
        expect(userId).toBeNull()
        expect(calls).toBe(0)
    })

    it('caches `null` when no slack integration is connected (treat as "lookup ran, no match")', async () => {
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ id: 'au-noslack' })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        // Empty integration store — no slack token for the team.
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: new MemoryIntegrationStore(),
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => 'bob@posthog.com',
        })
        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBeNull()
    })

    it('does NOT cache when the slack lookup throws — next event can retry', async () => {
        const integrations = new MemoryIntegrationStore()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ id: 'au-blip' })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => {
                throw new Error('slack: 500')
            },
        })
        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        // Lookup failed transiently, not cached. `undefined` (not `null`) so
        // the next event runs the bridge again.
        expect(cached!.posthog_user_id).toBeUndefined()
    })

    it('matches emails case-insensitively (Slack profile + PostHog stored case may differ)', async () => {
        const integrations = new MemoryIntegrationStore()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new MemoryIdentityStore()
        const agentUser = makeAgentUser({ id: 'au-case' })
        ;(identities as MemoryIdentityStore & { rows: AgentUser[] }).rows.push(agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'carol@posthog.com': 99 }),
            fetchSlackEmail: async () => 'Carol@PostHog.com',
        })
        expect(userId).toBe(99)
    })
})
