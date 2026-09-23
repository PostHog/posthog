/**
 * How a finished run is reported, and whether it gates.
 *
 * Lives outside index.ts so it can be tested directly: index.ts calls `program.parse()` at
 * import time, so importing it from a test would run the CLI.
 */
import { VisualReviewClient, type Run, type Snapshot } from './client.js'

// Log to stderr so stdout stays clean for machine-readable output (e.g. run IDs)
export function log(message: string): void {
    process.stderr.write(message + '\n')
}

// Enough to see the shape of a failure without burying the CI log when a global
// style change moves hundreds of stories at once.
const ACTIONABLE_SNAPSHOT_LOG_LIMIT = 25

/**
 * Name the snapshots that need review. The summary line above only carries counts, so
 * without this, reading a CI failure means opening the run in the UI, which does not work
 * for a run on a branch that no longer exists by the time anyone looks.
 *
 * `total` comes from the run summary rather than the fetched page, so the remainder stays
 * honest when a run has more actionable snapshots than one page holds.
 */
async function logActionableSnapshots(client: VisualReviewClient, runId: string, total: number): Promise<void> {
    let snapshots: Snapshot[]
    try {
        snapshots = await client.getRunSnapshots(runId)
    } catch (error) {
        log(`[run:${runId}] Could not list changed snapshots: ${error instanceof Error ? error.message : error}`)
        return
    }

    const actionable = snapshots.filter((snapshot) => snapshot.result !== 'unchanged')
    for (const snapshot of actionable.slice(0, ACTIONABLE_SNAPSHOT_LOG_LIMIT)) {
        const diff = snapshot.diff_percentage === null ? '' : ` (${snapshot.diff_percentage.toFixed(2)}% diff)`
        log(`[run:${runId}]   ${snapshot.result}: ${snapshot.identifier}${diff}`)
    }
    const remaining = total - Math.min(actionable.length, ACTIONABLE_SNAPSHOT_LOG_LIMIT)
    if (remaining > 0) {
        log(`[run:${runId}]   ...and ${remaining} more`)
    }
}

/**
 * Surface a warning where whoever is running the CLI will see it. `::warning::` goes to
 * stdout because that is the stream GitHub Actions parses for workflow commands; only
 * `run create` uses stdout for machine-readable output, so nothing here can corrupt it.
 */
function warn(message: string): void {
    if (process.env.GITHUB_ACTIONS === 'true') {
        process.stdout.write(`::warning::${message}\n`)
        return
    }
    log(`Warning: ${message}`)
}

/**
 * Report what the run found and return the exit code.
 *
 * Observe (tracking-only) runs have nothing to approve, so the backend reports zero unresolved
 * however many snapshots drifted. The drift still has to stop something. A merge-queue run
 * renders the tree that is about to land, so drift there is the merge moving pictures nobody
 * approved, and the job must fail.
 *
 * `tolerateDrift` exempts the default branch: no merge is left to stop there, and a red job
 * would block the repair too. Such a run still names the drift, because an identifier that
 * drifts on the default branch without being approved or quarantined reds the next PR that
 * renders it.
 *
 * The change counts are already the drift count on an observe run. A snapshot matching a
 * tolerated hash is reclassified `unchanged` by the server, so it never reaches `changed`, and
 * an observe run cannot approve or tolerate anything of its own (the API rejects both). So do
 * not net `tolerated_matched` off: it double-counts, and since it also spans quarantined
 * snapshots it goes negative on a clean run, which reads as drift. Quarantined snapshots are
 * excluded from the counts server-side.
 */
export async function reportRunOutcome(
    client: VisualReviewClient,
    run: Run,
    reviewUrl: string,
    purpose: string,
    tolerateDrift = false
): Promise<number> {
    const runId = run.id
    const s = run.summary
    const changes = s.changed + s.new + s.removed

    if (purpose === 'observe') {
        if (changes === 0) {
            log(`[run:${runId}] No visual changes`)
            return 0
        }
        await logActionableSnapshots(client, runId, changes)
        warn(
            `Unapproved snapshot drift on ${run.branch}: approve the new baseline, or quarantine the identifier if it flips between runs, before it fails an unrelated PR. Review at: ${reviewUrl}`
        )
        return tolerateDrift ? 0 : 1
    }

    const unresolved = s.unresolved ?? changes
    if (unresolved > 0) {
        await logActionableSnapshots(client, runId, unresolved)
        log(`[run:${runId}] Visual changes detected — review at: ${reviewUrl}`)
        return 1
    }

    log(`[run:${runId}] No visual changes`)
    return 0
}
