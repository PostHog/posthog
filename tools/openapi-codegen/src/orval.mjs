import { spawn } from 'node:child_process'

/**
 * Run a single Orval config file as a child process.
 * Returns a promise that resolves on success, rejects with stderr on failure.
 *
 * @param {string} configFile - absolute path to the Orval config
 * @param {string} cwd - working directory (repo root)
 * @returns {Promise<void>}
 */
function runOne(configFile, cwd) {
    return new Promise((resolve, reject) => {
        const child = spawn('pnpm', ['exec', 'orval', '--config', configFile], {
            stdio: 'pipe',
            cwd,
        })
        let stderr = ''
        child.stderr.on('data', (chunk) => {
            stderr += chunk
        })
        child.on('close', (code) => {
            if (code !== 0) {
                reject(new Error(`Orval exited with code ${code}: ${stderr}`))
            } else {
                resolve()
            }
        })
        child.on('error', reject)
    })
}

/**
 * Run multiple Orval config files in parallel with bounded concurrency.
 *
 * @param {Array<{configFile: string, label: string}>} jobs
 * @param {object} opts
 * @param {string} opts.cwd - working directory (repo root)
 * @param {number} [opts.concurrency=10] - max parallel Orval processes
 * @returns {Promise<Array<{status: 'fulfilled', label: string} | {status: 'rejected', label: string, reason: Error}>>}
 */
export async function runOrvalParallel(jobs, { cwd, concurrency = 10 }) {
    const results = []
    let index = 0

    async function worker() {
        while (index < jobs.length) {
            const i = index++
            const job = jobs[i]
            try {
                await runOne(job.configFile, cwd)
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
