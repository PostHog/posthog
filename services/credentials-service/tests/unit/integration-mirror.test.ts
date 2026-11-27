import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { type MirrorDecision, decideMirror } from '@/integrations/mirror'
import { type MirrorRowBody, mirrorBody } from '@/integrations/validation'

const TEAM = { type: 'team' as const, id: 101 }
const FIXTURE = JSON.parse(readFileSync(join(import.meta.dirname, '../fixtures/mirror-request.json'), 'utf8'))

function upsert(sourceVersion: number): MirrorRowBody {
    return {
        legacy_id: 1,
        deleted: false,
        source_version: sourceVersion,
        kind: 'slack',
        integration_id: 'T1',
        auth_type: 'oauth',
        is_source_row: false,
        config: {},
        sensitive_config: {},
        legacy_unreadable_keys: [],
        errors: '',
        created_by_id: null,
        created_at: '2024-01-01T00:00:00+00:00',
    }
}

function remove(tombstone: boolean, sourceVersion?: number): MirrorRowBody {
    const row: MirrorRowBody = { legacy_id: 1, deleted: true, kind: 'slack', tombstone }
    return sourceVersion === undefined ? row : { ...row, source_version: sourceVersion }
}

const live = (sourceVersion: number | null, ownerId = TEAM.id) => ({
    ownerType: 'team' as const,
    ownerId,
    deletedAt: null,
    sourceVersion,
})
const tombstone = { ownerType: 'team' as const, ownerId: TEAM.id, deletedAt: new Date(), sourceVersion: 3 }

describe('decideMirror', () => {
    it.each<[string, Parameters<typeof decideMirror>[0], MirrorRowBody, boolean, MirrorDecision]>([
        ['no row + upsert', null, upsert(1), false, { write: 'insert' }],
        ['no row + delete with tombstone', null, remove(true), false, { write: 'tombstone' }],
        ['no row + delete without tombstone', null, remove(false), false, { outcome: 'absent' }],
        ['tombstone + upsert', tombstone, upsert(99), true, { outcome: 'stale' }],
        ['tombstone + delete', tombstone, remove(true), false, { outcome: 'unchanged' }],
        ['live + delete', live(5), remove(false), false, { write: 'delete' }],
        ['live + delete with an equal version', live(5), remove(false, 5), false, { write: 'delete' }],
        ['live + delete with a lower version', live(5), remove(false, 4), false, { write: 'delete' }],
        ['live + lower version', live(5), upsert(4), true, { outcome: 'stale' }],
        ['live + equal version', live(5), upsert(5), false, { outcome: 'unchanged' }],
        ['live + equal version with force', live(5), upsert(5), true, { write: 'replace' }],
        ['live + higher version', live(5), upsert(6), false, { write: 'replace' }],
        ['live row the mirror never wrote', live(null), upsert(0), false, { write: 'replace' }],
        ['another team, live', live(5, 202), upsert(6), false, { outcome: 'owner_mismatch' }],
        ['another team, tombstone', { ...tombstone, ownerId: 202 }, remove(true), false, { outcome: 'owner_mismatch' }],
    ])('%s', (_name, stored, row, force, expected) => {
        expect(decideMirror(stored, row, TEAM, force)).toEqual(expected)
    })
})

describe('mirrorBody', () => {
    it('accepts the committed golden request as-is', () => {
        const result = mirrorBody.safeParse(FIXTURE)
        expect(result.error?.issues).toBeUndefined()
        expect(result.data).toEqual(FIXTURE)
    })

    it('accepts a Django external id longer than the create route allows', () => {
        const body = structuredClone(FIXTURE)
        body.rows[0].integration_id = Array.from({ length: 60 }, (_, i) => `7${String(i).padStart(9, '0')}`).join(',')
        expect(mirrorBody.safeParse(body).success).toBe(true)
    })

    it.each<[string, (body: any) => void]>([
        ['an unknown top-level field', (body) => (body.team_id = 1)],
        ['an unknown row field', (body) => (body.rows[0].owner = 2)],
        ['an unknown field on a delete row', (body) => (body.rows[2].auth_type = 'oauth')],
        ['an unknown origin', (body) => (body.origin = 'manual')],
        ['a missing source_version on an upsert', (body) => delete body.rows[0].source_version],
        ['a created_at without an offset', (body) => (body.rows[0].created_at = '2024-01-01T00:00:00')],
        ['a repeated legacy id', (body) => (body.rows[1].legacy_id = body.rows[0].legacy_id)],
        ['no rows', (body) => (body.rows = [])],
        [
            'more than 100 rows',
            (body) => (body.rows = Array.from({ length: 101 }, (_, i) => ({ ...body.rows[2], legacy_id: i + 1 }))),
        ],
    ])('refuses %s', (_name, mutate) => {
        const body = structuredClone(FIXTURE)
        mutate(body)
        expect(mirrorBody.safeParse(body).success).toBe(false)
    })
})
