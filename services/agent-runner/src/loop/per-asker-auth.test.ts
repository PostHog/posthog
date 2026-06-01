/**
 * Unit tests for the per-asker authorisation helper. The PostHog DB call is
 * stubbed; the contract under test is "does the helper correctly read the
 * most recent user-turn sender and resolve their authorisation."
 */

import { ConversationMessage, MemoryIdentityStore, SessionPrincipal } from '@posthog/agent-shared'

import { findLastUserSender, makePerAskerAuth } from './per-asker-auth'

function userMsg(content: string, sender?: SessionPrincipal): ConversationMessage {
    return { role: 'user', content, timestamp: Date.now(), sender }
}

function assistantMsg(text: string): ConversationMessage {
    return {
        role: 'assistant',
        content: [{ type: 'text', text }],
        timestamp: Date.now(),
    }
}

// Minimal stub matching the Pool surface `makePerAskerAuth` actually uses.
function fakePosthogDb(admins: Array<{ user_id: number; team_id: number }>): import('pg').Pool {
    return {
        async query(_sql: string, params: unknown[]) {
            const [userId, teamId] = params as [number, number]
            const found = admins.find((a) => a.user_id === userId && a.team_id === teamId)
            return found ? { rowCount: 1, rows: [{ one: 1 }] } : { rowCount: 0, rows: [] }
        },
    } as unknown as import('pg').Pool
}

describe('findLastUserSender', () => {
    it('returns the sender of the most recent user message that has one', () => {
        const sender = { kind: 'slack' as const, workspace_id: 'T_1', slack_user_id: 'au-bob', agent_user_id: 'au-bob' }
        const sender2 = {
            kind: 'slack' as const,
            workspace_id: 'T_1',
            slack_user_id: 'au-carol',
            agent_user_id: 'au-carol',
        }
        const conv = [userMsg('first', sender), assistantMsg('reply'), userMsg('second', sender2)]
        expect(findLastUserSender(conv)).toEqual(sender2)
    })

    it('skips synthetic user messages with no sender (sweep wakes, etc.)', () => {
        const sender = {
            kind: 'slack' as const,
            workspace_id: 'T_1',
            slack_user_id: 'au-carol',
            agent_user_id: 'au-carol',
        }
        const conv = [userMsg('alice asked', sender), assistantMsg('replying'), userMsg('synthetic wake')]
        // Synthetic wake has no sender — fall back to the real prior asker.
        expect(findLastUserSender(conv)).toEqual(sender)
    })

    it('returns null when no user message has a sender', () => {
        const conv = [userMsg('legacy message, no sender')]
        expect(findLastUserSender(conv)).toBeNull()
    })

    it('returns null for an empty conversation', () => {
        expect(findLastUserSender([])).toBeNull()
    })
})

describe('makePerAskerAuth', () => {
    async function makeStoreWithAdmin(adminAgentUserId: string, posthogUserId: number): Promise<MemoryIdentityStore> {
        const store = new MemoryIdentityStore()
        const user = await store.findOrCreate({
            team_id: 7,
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-CAROL',
        })
        // Rebind the id so callers can stamp it on conversation senders.
        // MemoryIdentityStore mints a fresh uuid; we'd rather control it.
        await store.setPosthogUserId(user.id, posthogUserId)
        return store
    }

    it('returns true when the asker is a slack-mapped team admin', async () => {
        const store = await makeStoreWithAdmin('ignored', 42)
        const carol = await store.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-CAROL',
        })
        const isAuthed = makePerAskerAuth({
            identities: store,
            posthogDb: fakePosthogDb([{ user_id: 42, team_id: 7 }]),
        })
        const conv = [
            userMsg('do the thing', {
                kind: 'slack' as const,
                workspace_id: 'T_7',
                slack_user_id: carol!.id,
                agent_user_id: carol!.id,
            }),
        ]
        expect(await isAuthed(conv, 7, ['team_admins'])).toBe(true)
    })

    it('returns false when the asker is mapped but not a team admin on this team', async () => {
        const store = await makeStoreWithAdmin('ignored', 42)
        const carol = await store.find({
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-CAROL',
        })
        // Carol is admin on team 7, but the question is about team 99.
        const isAuthed = makePerAskerAuth({
            identities: store,
            posthogDb: fakePosthogDb([{ user_id: 42, team_id: 7 }]),
        })
        const conv = [
            userMsg('do the thing', {
                kind: 'slack' as const,
                workspace_id: 'T_99',
                slack_user_id: carol!.id,
                agent_user_id: carol!.id,
            }),
        ]
        expect(await isAuthed(conv, 99, ['team_admins'])).toBe(false)
    })

    it('returns false when no AgentUser exists for the sender id', async () => {
        const store = new MemoryIdentityStore()
        const isAuthed = makePerAskerAuth({
            identities: store,
            posthogDb: fakePosthogDb([]),
        })
        const conv = [
            userMsg('ghost asker', {
                kind: 'slack' as const,
                workspace_id: 'T_7',
                slack_user_id: 'nonexistent-uuid',
                agent_user_id: 'nonexistent-uuid',
            }),
        ]
        expect(await isAuthed(conv, 7, ['team_admins'])).toBe(false)
    })

    it('returns false when the AgentUser exists but has no posthog_user_id (external slack member)', async () => {
        const store = new MemoryIdentityStore()
        const ext = await store.findOrCreate({
            team_id: 7,
            application_id: 'app',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-EXTERNAL',
        })
        // Bridge ran but found no match → cached null.
        await store.setPosthogUserId(ext.id, null)
        const isAuthed = makePerAskerAuth({
            identities: store,
            posthogDb: fakePosthogDb([{ user_id: 999, team_id: 7 }]),
        })
        const conv = [
            userMsg('external request', {
                kind: 'slack' as const,
                workspace_id: 'T_7',
                slack_user_id: ext.id,
                agent_user_id: ext.id,
            }),
        ]
        expect(await isAuthed(conv, 7, ['team_admins'])).toBe(false)
    })

    it('returns false for non-slack principals (service, internal, etc.)', async () => {
        // PAT-based self-authorisation is a sensible follow-up but isn't
        // implemented in v0. Asking via a PAT today still queues.
        const isAuthed = makePerAskerAuth({
            identities: new MemoryIdentityStore(),
            posthogDb: fakePosthogDb([{ user_id: 42, team_id: 7 }]),
        })
        const conv = [userMsg('via pat', { kind: 'service', team_id: 7, id: 'pat-carol' })]
        expect(await isAuthed(conv, 7, ['team_admins'])).toBe(false)
    })

    it('returns false when no user-turn carries a sender (legacy rows)', async () => {
        const isAuthed = makePerAskerAuth({
            identities: new MemoryIdentityStore(),
            posthogDb: fakePosthogDb([]),
        })
        // Both messages predate per-message stamping.
        const conv = [userMsg('legacy'), userMsg('also legacy')]
        expect(await isAuthed(conv, 7, ['team_admins'])).toBe(false)
    })

    it('returns false when the approver scope does not include team_admins (v0 only handles team_admins)', async () => {
        const isAuthed = makePerAskerAuth({
            identities: new MemoryIdentityStore(),
            posthogDb: fakePosthogDb([]),
        })
        const conv = [
            userMsg('q', {
                kind: 'slack' as const,
                workspace_id: 'T_7',
                slack_user_id: 'au-id',
                agent_user_id: 'au-id',
            }),
        ]
        expect(await isAuthed(conv, 7, ['session_owner'])).toBe(false)
        expect(await isAuthed(conv, 7, [])).toBe(false)
    })
})
