/** Matrix grouping for GitHub Actions jobs, derived from real PostHog run shapes.
 *
 *  A master-push Backend CI run carries ~80 jobs; most are matrix shards. Grouping rules:
 *  - a trailing "(G/N)" shard suffix is stripped — including when nested inside another paren
 *    group, e.g. "Product tests (experiments (1/2))" → "Product tests (experiments)"
 *  - jobs group by the base name before the first " – " or " (" of the de-sharded name,
 *    so "Django tests – Core (persons-on-events off), Py 3.13 (3/23)" and its Temporal
 *    sibling land in one "Django tests" group with two variants
 *  - a skipped matrix never expands, so its single job keeps the raw workflow-file template
 *    name ("Django tests – ${{ matrix.segment }} …"); templates are collapsed to "…" for
 *    display but still group by their base
 */

export interface GroupableJob {
    name: string
    /** null while the job is still running */
    conclusion: string | null
}

export type JobGroupConclusion = 'failure' | 'running' | 'cancelled' | 'skipped' | 'success'

export interface JobGroup<T extends GroupableJob> {
    /** grouping key and display name: de-sharded, de-templated base */
    base: string
    jobs: T[]
    /** distinct matrix variants inside the group (segment/python/etc. combos) */
    variants: number
    failed: T[]
    conclusion: JobGroupConclusion
}

/** Strip a trailing "(G/N)" shard suffix, preserving a closing paren that wrapped it. */
export function stripShardSuffix(name: string): string {
    return name.replace(/\s*\((\d+)\/(\d+)\)(\))?$/, (_, __, ___, close: string | undefined) => (close ? ')' : ''))
}

/** Collapse unexpanded workflow-file templates ("${{ matrix.foo }}") for display. */
export function collapseTemplates(name: string): string {
    return name
        .replace(/\$\{\{[^}]*\}\}/g, '…')
        .replace(/\s+/g, ' ')
        .trim()
}

/** The grouping key: de-sharded, de-templated, cut before the first " – " or " (". */
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

/** Group jobs by matrix base, preserving first-appearance order of the groups. */
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

/** Short human form of which shards failed inside a group: "shards 3, 17 of 23". */
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
