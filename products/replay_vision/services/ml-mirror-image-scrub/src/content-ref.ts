// Content reference for an inlined replay image: the worker swaps the raw `rr_dataURL` for one of these,
// the consumer scrubs it into a team-scoped shard, and training resolves block -> image via the team's
// parquet index (see shard-store.ts). Format `image:{team_id}:{hash}`, hash = 132-bit sha256, base64url,
// 22 chars. The team_id prefix is load-bearing for tenant isolation: identical bytes in two teams produce
// two references and never share a shard/index entry.
import { createHash } from 'node:crypto'

const PREFIX = 'image'
const REF_RE = /^image:(\d+):([A-Za-z0-9_-]{22})$/

/** Content-only hash (not team-scoped); the reference's team prefix provides per-tenant separation. */
export function hashImageBytes(bytes: Buffer): string {
    return createHash('sha256').update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(teamId: number, hash: string): string {
    return `${PREFIX}:${teamId}:${hash}`
}

export function isImageRef(s: string): boolean {
    return REF_RE.test(s)
}

export function parseImageRef(ref: string): { teamId: number; hash: string } | null {
    const m = REF_RE.exec(ref)
    return m ? { teamId: Number(m[1]), hash: m[2] } : null
}
