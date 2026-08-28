import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/workflows'

// The backend serializes concurrent workflow writes and rejects a stale one with a 409, but only
// when the caller sends base_updated_at. If a tool schema drops that field, the token never reaches
// the API and two concurrent MCP edits silently clobber each other. These tests pin the field onto
// the two write tools that carry it, so a codegen change can't quietly reopen the race.
describe('workflow write tools carry the optimistic-concurrency token', () => {
    it('workflows-patch-graph keeps base_updated_at through its schema', () => {
        const schema = GENERATED_TOOLS['workflows-patch-graph']!().schema
        const parsed = schema.parse({
            id: 'flow-1',
            operations: [{ op: 'remove_action', id: 'step-1' }],
            base_updated_at: '2026-08-28T00:00:00Z',
        })
        expect(parsed.base_updated_at).toBe('2026-08-28T00:00:00Z')
    })

    it('workflows-update keeps base_updated_at through its schema', () => {
        const schema = GENERATED_TOOLS['workflows-update']!().schema
        const parsed = schema.parse({
            id: 'flow-1',
            name: 'Renamed',
            base_updated_at: '2026-08-28T00:00:00Z',
        })
        expect(parsed.base_updated_at).toBe('2026-08-28T00:00:00Z')
    })
})
