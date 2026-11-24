import { type ModelLab, modelLab } from '../aiLabs'

export interface BucketedFacetRow {
    bucket: string
    label: string
    calls: number
}

export interface LabShare {
    lab: ModelLab
    share: number
    // The lab's calls or users, out of `total`, the denominator of `share`.
    count: number
    total: number
}

export interface LabUsersRow {
    lab: string
    users: number
}

export type ScoreboardMetric = 'calls' | 'users'

const UNKNOWN = 'Unknown'

export function buildLabShares(rows: BucketedFacetRow[]): LabShare[] {
    const callsByLab = new Map<ModelLab, number>()
    for (const row of rows) {
        if (row.label !== UNKNOWN) {
            const lab = modelLab(row.label)
            callsByLab.set(lab, (callsByLab.get(lab) ?? 0) + row.calls)
        }
    }
    const total = [...callsByLab.values()].reduce((sum, calls) => sum + calls, 0)
    return [...callsByLab.entries()]
        .filter(([lab]) => lab !== 'Other')
        .sort(([, a], [, b]) => b - a)
        .map(([lab, calls]) => ({ lab, share: total > 0 ? (calls / total) * 100 : 0, count: calls, total }))
}

// A person can use models from several labs, so these shares do not add up to 100.
export function buildLabUserShares(rows: LabUsersRow[], namedModelUsers: number): LabShare[] {
    return rows
        .filter((row): row is { lab: ModelLab; users: number } => row.lab !== UNKNOWN && row.lab !== 'Other')
        .sort((a, b) => b.users - a.users)
        .map(({ lab, users }) => ({
            lab,
            share: namedModelUsers > 0 ? (users / namedModelUsers) * 100 : 0,
            count: users,
            total: namedModelUsers,
        }))
}

export function leadingLabs(shares: LabShare[]): ModelLab[] {
    const topShare = Math.max(0, ...shares.map(({ share }) => share))
    return topShare > 0 ? shares.filter(({ share }) => share === topShare).map(({ lab }) => lab) : []
}

/** Share of blank calls at which a chart asks for setup. */
export const MOSTLY_MISSING_SHARE = 0.9

/** Whether nearly every call falls under one of `labels`, such as "Unknown". False with no calls. */
export function isMostlyLabeled(rows: Pick<BucketedFacetRow, 'label' | 'calls'>[], labels: string[]): boolean {
    const total = rows.reduce((sum, row) => sum + row.calls, 0)
    const labeled = rows.reduce((sum, row) => sum + (labels.includes(row.label) ? row.calls : 0), 0)
    return total > 0 && labeled / total >= MOSTLY_MISSING_SHARE
}

export interface ShareSeries {
    label: string
    data: number[]
}

const OTHER = 'Other'

// `groupOf` returns null to drop a row. The top `limit` groups by total calls keep their own series
// and the rest fold into one "Other" series, which is always last.
export function buildShareSeries(
    rows: BucketedFacetRow[],
    bucketKeys: string[],
    groupOf: (label: string) => string | null,
    limit: number
): ShareSeries[] {
    const bucketIndex = new Map(bucketKeys.map((key, index) => [key, index]))
    const byGroup = new Map<string, number[]>()
    for (const row of rows) {
        const group = groupOf(row.label)
        const index = bucketIndex.get(row.bucket)
        if (group === null || index === undefined) {
            continue
        }
        const data = byGroup.get(group) ?? bucketKeys.map(() => 0)
        data[index] += row.calls
        byGroup.set(group, data)
    }
    const total = (data: number[]): number => data.reduce((sum, value) => sum + value, 0)
    const ranked = [...byGroup.entries()]
        .filter(([group]) => group !== OTHER)
        .sort(([, a], [, b]) => total(b) - total(a))
    const series: ShareSeries[] = ranked.slice(0, limit).map(([label, data]) => ({ label, data }))
    const folded = [
        ...ranked.slice(limit).map(([, data]) => data),
        ...(byGroup.has(OTHER) ? [byGroup.get(OTHER)!] : []),
    ]
    if (folded.length > 0) {
        series.push({
            label: OTHER,
            data: bucketKeys.map((_, index) => folded.reduce((sum, data) => sum + data[index], 0)),
        })
    }
    return series
}
