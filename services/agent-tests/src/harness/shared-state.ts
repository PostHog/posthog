import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * State the jest globalSetup writes for test workers to read.
 *
 * Jest globalSetup runs in a separate process from the test workers, so a
 * module-level singleton there isn't visible to tests. We persist the
 * runtime knobs (port, internal secret, queue name, pids) to a known
 * tmpfile; `getSharedCluster()` reads it on first call inside each
 * worker, and `globalTeardown` reads the pids to SIGTERM the bins.
 */
export interface SharedClusterState {
    ingressUrl: string
    port: number
    internalSecret: string
    queueName: string
    ingressPid: number
    runnerPid: number
    /** Absolute path the bins write logs to. Tests can `tail -f` for debugging. */
    ingressLog: string
    runnerLog: string
}

export const SHARED_STATE_PATH = join(tmpdir(), 'agent-tests-shared-cluster.json')

export function writeSharedState(state: SharedClusterState): void {
    writeFileSync(SHARED_STATE_PATH, JSON.stringify(state, null, 2))
}

export function readSharedState(): SharedClusterState {
    if (!existsSync(SHARED_STATE_PATH)) {
        throw new Error(
            `shared cluster state file ${SHARED_STATE_PATH} not found — was jest started with the right globalSetup?`
        )
    }
    return JSON.parse(readFileSync(SHARED_STATE_PATH, 'utf8')) as SharedClusterState
}

export function clearSharedState(): void {
    if (existsSync(SHARED_STATE_PATH)) {
        unlinkSync(SHARED_STATE_PATH)
    }
}
