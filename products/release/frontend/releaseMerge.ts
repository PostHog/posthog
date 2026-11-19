import type { ReleaseDTOApi } from './generated/api.schemas'
import { ReleaseRow } from './releaseUtils'

export const MERGE_SOURCE_LIMIT = 100
export const MERGE_LIMIT_REASON = `Merge at most ${MERGE_SOURCE_LIMIT} releases into one at a time`

export interface MergeCandidate {
    id: string
    name: string
    summary: string
    linked: number
}

function counted(count: number, one: string, many: string): string | null {
    return count ? `${count} ${count === 1 ? one : many}` : null
}

export function mergeCandidate(row: ReleaseRow, release: ReleaseDTOApi | undefined): MergeCandidate {
    const counts: [number, string, string][] = [
        [release?.feature_flag_ids.length ?? row.flags.length, 'flag', 'flags'],
        [row.experiments.length, 'experiment', 'experiments'],
        [row.earlyAccess.length, 'early access feature', 'early access features'],
        [release?.survey_ids.length ?? 0, 'survey', 'surveys'],
        [release?.insight_ids.length ?? 0, 'insight', 'insights'],
        [release?.broadcast_ids.length ?? 0, 'broadcast', 'broadcasts'],
    ]
    const parts = counts.map(([count, one, many]) => counted(count, one, many)).filter(Boolean)
    return {
        id: row.id,
        name: row.name,
        summary: parts.join(', ') || 'Nothing linked yet',
        linked: counts.reduce((total, [count]) => total + count, 0),
    }
}

export function releaseToKeep(candidates: MergeCandidate[]): string | null {
    return (
        candidates.reduce<MergeCandidate | null>(
            (best, candidate) => (!best || candidate.linked > best.linked ? candidate : best),
            null
        )?.id ?? null
    )
}
