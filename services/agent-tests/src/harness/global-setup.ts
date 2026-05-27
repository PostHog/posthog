/* eslint-disable no-console */
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { spawnBins } from './cluster'
import { writeSharedState } from './shared-state'

/**
 * Jest globalSetup — boots ONE ingress + ONE runner that every test
 * suite shares. The router test executor dispatches per-app based on
 * `__TEST_EXECUTOR` in the app's encrypted_env, so a single runner
 * serves principal-echo, slow-cancellable, failure, SDK, and echo apps
 * concurrently. This matches production (one ingress + one runner serve
 * many apps) AND amortises subprocess spawn cost across all 13 suites.
 *
 * The bins outlive this globalSetup process — jest forks workers next
 * — so we write their PIDs + connection knobs to a tmpfile (read by
 * `openSharedCluster()` in tests and by `globalTeardown` for shutdown).
 *
 * stdout/stderr go to log files for the same reason: parent (jest)
 * stdio doesn't survive the worker handoff. Tail with `tail -f`.
 */
export default async function globalSetup(): Promise<void> {
    const ingressLog = join(tmpdir(), 'agent-tests-ingress.log')
    const runnerLog = join(tmpdir(), 'agent-tests-runner.log')

    console.log('[agent-tests] booting shared cluster (ingress + runner)…')
    const start = Date.now()
    const spawned = await spawnBins({
        executor: 'router',
        env: {
            // Threaded only if set in the parent env. Stub executors don't
            // need it; the SDK kind does. Missing key + SDK app → clear
            // failure from the Anthropic SDK at runtime, not a
            // pre-flight refusal.
            ...(process.env.ANTHROPIC_API_KEY ? { ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY } : {}),
            ANTHROPIC_MODEL: process.env.AGENT_E2E_MODEL ?? 'claude-haiku-4-5',
            AGENT_RUNNER_TOOL_SANDBOX: process.env.AGENT_RUNNER_TOOL_SANDBOX ?? 'docker',
        },
        logFiles: { ingress: ingressLog, runner: runnerLog },
    })

    if (!spawned.ingressProc?.pid || !spawned.runnerProc?.pid) {
        throw new Error('globalSetup: spawnBins returned without PIDs — refusing to write incomplete state')
    }

    writeSharedState({
        ingressUrl: spawned.ingressUrl,
        port: spawned.port,
        internalSecret: spawned.internalSecret,
        queueName: spawned.queueName,
        ingressPid: spawned.ingressProc.pid,
        runnerPid: spawned.runnerProc.pid,
        ingressLog,
        runnerLog,
    })

    // Detach the child handles so the globalSetup process can exit
    // without sending SIGHUP. The bins keep running; globalTeardown
    // signals them by PID.
    spawned.ingressProc.unref()
    spawned.runnerProc.unref()

    console.log(
        `[agent-tests] shared cluster ready in ${Date.now() - start}ms — ingress=${spawned.ingressUrl} (pid ${spawned.ingressProc.pid}) runner pid=${spawned.runnerProc.pid}`
    )
    console.log(`[agent-tests]   ingress log: tail -f ${ingressLog}`)
    console.log(`[agent-tests]   runner  log: tail -f ${runnerLog}`)
}
