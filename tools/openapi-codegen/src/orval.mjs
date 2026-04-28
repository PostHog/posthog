import { generate } from 'orval'

/**
 * Run multiple Orval generations in parallel using Orval's JS API.
 *
 * Calls `generate()` in-process — avoids spawning a child process per
 * module, saving ~0.6s of Node/pnpm startup overhead per invocation.
 *
 * @param {Array<{config: object, label: string}>} jobs
 *   Each `config` is an Orval config object: `{ input, output }`.
 * @param {object} [opts]
 * @param {number} [opts.concurrency=10] - max parallel Orval generations
 * @returns {Promise<Array<{status: 'fulfilled', label: string} | {status: 'rejected', label: string, reason: Error}>>}
 */
export async function runOrvalParallel(jobs, { concurrency = 10 } = {}) {
    if (jobs.length === 0) {
        return []
    }
    concurrency = Math.max(1, concurrency)

    const results = []
    let index = 0

    async function worker() {
        while (index < jobs.length) {
            const i = index++
            const job = jobs[i]
            try {
                await generate(job.config)
                results[i] = { status: 'fulfilled', label: job.label }
            } catch (err) {
                results[i] = { status: 'rejected', label: job.label, reason: err }
            }
        }
    }

    const workers = Array.from({ length: Math.min(concurrency, jobs.length) }, () => worker())
    await Promise.all(workers)
    return results
}
