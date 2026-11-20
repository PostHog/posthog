/**
 * Grouping rules for GitHub Actions matrix jobs:
 * - A trailing "(G/N)" shard suffix is stripped, also when it is nested inside another paren group.
 *   "Product tests (experiments (1/2))" becomes "Product tests (experiments)".
 * - Jobs group by the base name before the first " – " or " (" of the de-sharded name.
 * - A skipped matrix never expands, so its single job keeps the raw workflow-file template name
 *   ("Django tests – ${{ matrix.segment }} …"). A template collapses to "…" for display but still
 *   groups by its base.
 */

export interface GroupableJob {
    name: string
    /** Null while the job is still running. */
    conclusion: string | null
}

export type JobGroupConclusion = 'failure' | 'running' | 'cancelled' | 'skipped' | 'success'

export interface JobGroup<T extends GroupableJob> {
    base: string
    jobs: T[]
    variants: number
    failed: T[]
    conclusion: JobGroupConclusion
}

export function stripShardSuffix(name: string): string {
    return name.replace(/\s*\((\d+)\/(\d+)\)(\))?$/, (_, __, ___, close: string | undefined) => (close ? ')' : ''))
}

export function collapseTemplates(name: string): string {
    return name
        .replace(/\$\{\{[^}]*\}\}/g, '…')
        .replace(/\s+/g, ' ')
        .trim()
}

export function jobBaseName(name: string): string {
    const cleaned = collapseTemplates(stripShardSuffix(name))
    const cuts = [cleaned.indexOf(' – '), cleaned.indexOf(' (')].filter((i) => i > 0)
    return (cuts.length ? cleaned.slice(0, Math.min(...cuts)) : cleaned).trim()
}

function groupConclusion(jobs: GroupableJob[]): JobGroupConclusion {
    const conclusions = jobs.map((j) => j.conclusion)
    if (conclusions.some((c) => c === 'failure' || c === 'timed_out')) {
        return 'failure'
    }
    if (conclusions.some((c) => c === null)) {
        return 'running'
    }
    if (conclusions.some((c) => c === 'cancelled')) {
        return 'cancelled'
    }
    if (conclusions.every((c) => c === 'skipped')) {
        return 'skipped'
    }
    return 'success'
}

export function groupJobs<T extends GroupableJob>(jobs: T[]): JobGroup<T>[] {
    const order: string[] = []
    const byBase = new Map<string, T[]>()
    for (const job of jobs) {
        const base = jobBaseName(job.name)
        if (!byBase.has(base)) {
            byBase.set(base, [])
            order.push(base)
        }
        byBase.get(base)!.push(job)
    }
    return order.map((base) => {
        const group = byBase.get(base)!
        return {
            base,
            jobs: group,
            variants: new Set(group.map((j) => collapseTemplates(stripShardSuffix(j.name)))).size,
            failed: group.filter((j) => j.conclusion === 'failure' || j.conclusion === 'timed_out'),
            conclusion: groupConclusion(group),
        }
    })
}

/** For example "shards 3, 17 of 23". */
export function failedShardsLabel<T extends GroupableJob>(group: JobGroup<T>): string {
    const shardMatches = group.failed
        .map((j) => j.name.match(/\((\d+)\/(\d+)\)\)?$/))
        .filter((m): m is RegExpMatchArray => m !== null)
    if (!shardMatches.length) {
        return group.failed.map((j) => collapseTemplates(j.name)).join(' · ')
    }
    const nums = shardMatches.map((m) => m[1])
    const total = shardMatches[0][2]
    return `shard${nums.length > 1 ? 's' : ''} ${nums.join(', ')} of ${total}`
}
