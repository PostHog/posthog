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
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(true)
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
        expect(await isAuthed(conv, 99, ['team_admins'], null)).toBe(false)
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
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(false)
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
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false for non-slack principals (service, internal, etc.)', async () => {
        // PAT-based self-authorisation is a sensible follow-up but isn't
        // implemented in v0. Asking via a PAT today still queues.
        const isAuthed = makePerAskerAuth({
            identities: new MemoryIdentityStore(),
            posthogDb: fakePosthogDb([{ user_id: 42, team_id: 7 }]),
        })
        const conv = [userMsg('via pat', { kind: 'service', team_id: 7, id: 'pat-carol' })]
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false when no user-turn carries a sender (legacy rows)', async () => {
        const isAuthed = makePerAskerAuth({
            identities: new MemoryIdentityStore(),
            posthogDb: fakePosthogDb([]),
        })
        // Both messages predate per-message stamping.
        const conv = [userMsg('legacy'), userMsg('also legacy')]
        expect(await isAuthed(conv, 7, ['team_admins'], null)).toBe(false)
    })

    it('returns false when the approver scope does not include team_admins or session_principal', async () => {
        // v0 supports two scopes: `team_admins` (B.2 v0) and
        // `session_principal` (PR 7). Anything else falls through to false
        // without touching the identity store or the posthog DB.
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
        // `session_owner` isn't in the v0 enum (would be rejected by zod
        // before reaching here); we still want the runner to fail closed if
        // a stray scope slips through validation.
        expect(await isAuthed(conv, 7, ['session_owner'], null)).toBe(false)
        expect(await isAuthed(conv, 7, [], null)).toBe(false)
    })

    describe('session_principal scope (PR 7 — concierge fast-path)', () => {
        const alice: SessionPrincipal = {
            kind: 'posthog',
            source: 'oauth',
            user_id: 'alice',
            team_id: 7,
        }
        const bob: SessionPrincipal = {
            kind: 'posthog',
            source: 'oauth',
            user_id: 'bob',
            team_id: 7,
        }

        it('returns true when the session principal matches the most recent user-turn sender', async () => {
            // Alice authed the session and is the one driving the current
            // turn — fast-path authorises without touching the posthog DB
            // (the fake's query throws if called).
            const isAuthed = makePerAskerAuth({
                identities: new MemoryIdentityStore(),
                posthogDb: {
                    async query() {
                        throw new Error('should not hit posthog DB on the session_principal fast path')
                    },
                } as unknown as import('pg').Pool,
            })
            const conv = [userMsg('promote it', alice)]
            expect(await isAuthed(conv, 7, ['session_principal'], alice)).toBe(true)
        })

        it('returns false when the last sender is a different principal than the session owner', async () => {
            // The trigger edge already enforces strict-principal match on
            // /send, so in practice we expect alice's session to only ever
            // see alice's senders. Belt-and-braces: if a sender for bob
            // somehow lands in alice's session, the session_principal scope
            // still rejects.
            const isAuthed = makePerAskerAuth({
                identities: new MemoryIdentityStore(),
                posthogDb: fakePosthogDb([]),
            })
            const conv = [userMsg('promote it', bob)]
            expect(await isAuthed(conv, 7, ['session_principal'], alice)).toBe(false)
        })

        it('returns false when sessionPrincipal is null (public agent — nothing to compare against)', async () => {
            const isAuthed = makePerAskerAuth({
                identities: new MemoryIdentityStore(),
                posthogDb: fakePosthogDb([]),
            })
            const conv = [userMsg('promote it', alice)]
            expect(await isAuthed(conv, 7, ['session_principal'], null)).toBe(false)
        })

        it('returns false for anonymous principals (public agent — every caller would otherwise self-authorise)', async () => {
            // The public verifier stores { kind: 'anonymous' } — not null — on
            // the session row and stamps the same sender on the user turn.
            // principalsMatch(anonymous, anonymous) is true, so without the
            // explicit exclusion every public caller would clear the gate.
            const anon: SessionPrincipal = { kind: 'anonymous' }
            const isAuthed = makePerAskerAuth({
                identities: new MemoryIdentityStore(),
                posthogDb: fakePosthogDb([]),
            })
            const conv = [userMsg('promote it', anon)]
            expect(await isAuthed(conv, 7, ['session_principal'], anon)).toBe(false)
        })

        it('falls through to team_admins when session_principal does not match but team_admins is in scope', async () => {
            // Mixed-scope policy: session principal OR team admin. The
            // session principal slot doesn't match (bob's sender vs alice's
            // session), so we fall through and resolve team_admins via the
            // existing path. Alice is configured as a team admin on team 7
            // via the posthog-DB fake.
            const store = new MemoryIdentityStore()
            const senderAgent = await store.findOrCreate({
                team_id: 7,
                application_id: 'app',
                principal_kind: 'slack',
                principal_id: 'T01:U-ADMIN',
            })
            await store.setPosthogUserId(senderAgent.id, 99)
            const isAuthed = makePerAskerAuth({
                identities: store,
                posthogDb: fakePosthogDb([{ user_id: 99, team_id: 7 }]),
            })
            const conv = [
                userMsg('approve it', {
                    kind: 'slack' as const,
                    workspace_id: 'T01',
                    slack_user_id: senderAgent.id,
                    agent_user_id: senderAgent.id,
                }),
            ]
            expect(await isAuthed(conv, 7, ['session_principal', 'team_admins'], alice)).toBe(true)
        })
    })
})
