/* eslint-disable no-console */
import { clearSharedState, readSharedState } from './shared-state'

/**
 * Jest globalTeardown — SIGTERMs the bins spawned by globalSetup.
 * Reads PIDs from the shared-state tmpfile; if the file is gone (the
 * tests crashed before setup could write it) the teardown is a no-op.
 */
export default async function globalTeardown(): Promise<void> {
    let state
    try {
        state = readSharedState()
    } catch {
        // No state file — globalSetup never wrote one. Nothing to do.
        return
    }

    console.log(
        `[agent-tests] tearing down shared cluster (pids ingress=${state.ingressPid}, runner=${state.runnerPid})…`
    )
    await Promise.all([
        signalAndWait(state.ingressPid, 'agent-ingress'),
        signalAndWait(state.runnerPid, 'agent-runner'),
    ])
    clearSharedState()
}

async function signalAndWait(pid: number, name: string): Promise<void> {
    if (!alive(pid)) {
        return
    }
    try {
        process.kill(pid, 'SIGTERM')
    } catch {
        return
    }
    // Poll for exit, then SIGKILL after grace.
    const start = Date.now()
    while (Date.now() - start < 5_000) {
        if (!alive(pid)) {
            return
        }
        await new Promise((r) => setTimeout(r, 100))
    }
    console.warn(`[agent-tests] ${name} (pid ${pid}) did not exit within grace period — SIGKILL`)
    try {
        process.kill(pid, 'SIGKILL')
    } catch {
        /* race: already gone */
    }
}

function alive(pid: number): boolean {
    try {
        process.kill(pid, 0)
        return true
    } catch {
        return false
    }
}
