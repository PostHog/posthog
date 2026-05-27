/* eslint-disable no-console */
import { createServer } from 'node:net'
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

    // Reserve a port for the mock Anthropic server. The test worker
    // (a different process from globalSetup) lazily binds this port
    // when the first test imports `getMockAnthropic()`. The bins boot
    // pointing at this URL, but the mock isn't required to be up at
    // boot time — the SDK only hits it when an agent actually runs.
    const mockAnthropicPort = await pickFreePort()
    const mockAnthropicUrl = `http://127.0.0.1:${mockAnthropicPort}`

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
            // Point the SDK at the in-process mock. `mock-*` model
            // names get served from built-ins; real `claude-*` model
            // names fall through to the mock's proxy upstream
            // (`api.anthropic.com`).
            ANTHROPIC_BASE_URL: mockAnthropicUrl,
            AGENT_RUNNER_TOOL_SANDBOX: process.env.AGENT_RUNNER_TOOL_SANDBOX ?? 'docker',
            // agent-core's logger defaults to `silent` when NODE_ENV=test
            // (which jest sets). The runner subprocess is a separate
            // process and we DO want its logs — timing markers, errors,
            // boot info. Force info-level unless overridden.
            LOG_LEVEL: process.env.AGENT_TESTS_RUNNER_LOG_LEVEL ?? 'info',
            NODE_ENV: 'development',
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
        mockAnthropicUrl,
        mockAnthropicPort,
    })

    // Detach the child handles so the globalSetup process can exit
    // without sending SIGHUP. The bins keep running; globalTeardown
    // signals them by PID.
    spawned.ingressProc.unref()
    spawned.runnerProc.unref()

    console.log(
        `[agent-tests] shared cluster ready in ${Date.now() - start}ms — ingress=${spawned.ingressUrl} (pid ${spawned.ingressProc.pid}) runner pid=${spawned.runnerProc.pid} mock-anthropic=${mockAnthropicUrl} (bound lazily in test worker)`
    )
    console.log(`[agent-tests]   ingress log: tail -f ${ingressLog}`)
    console.log(`[agent-tests]   runner  log: tail -f ${runnerLog}`)
}

/** Reserve a free TCP port the OS hands back. Same logic as cluster.ts. */
async function pickFreePort(): Promise<number> {
    return new Promise<number>((resolve, reject) => {
        const srv = createServer()
        srv.unref()
        srv.on('error', reject)
        srv.listen(0, '127.0.0.1', () => {
            const addr = srv.address()
            if (addr && typeof addr === 'object') {
                const { port } = addr
                srv.close(() => resolve(port))
            } else {
                reject(new Error('pickFreePort: address() returned a non-object'))
            }
        })
    })
}
