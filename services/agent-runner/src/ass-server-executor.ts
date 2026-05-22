import { loadCompiledAgent } from '@repo/ass-server/load-compiled-agent'
import { runSession } from '@repo/ass-server/session-runner'

import {
    ApplicationsRepository,
    BundleStore,
    LogProducer,
    ResolvedRevision,
    SessionBus,
    createSessionLogger,
    extractBundleToTempDir,
    logger,
} from '@posthog/agent-core'

import { BusBridgingRegistry } from './ass-server-bridge'
import { ExecutorTurnInput, ExecutorTurnOutput, SessionExecutor } from './executor'
import { makeToolSandboxFactory } from './tool-sandbox'

export interface AssServerExecutorOptions {
    bundleStore: BundleStore
    repository: ApplicationsRepository
    bus: SessionBus
    logProducer: LogProducer
}

/**
 * Real executor for PostHog's agent runner: downloads the revision's bundle from
 * object storage, loads it with `@repo/ass-config`, and hands the result to
 * `runSession()` (ass-server's whole-session loop powered by the Claude Agent SDK).
 *
 * Custom (local) tools run sandboxed: the executor picks a provider
 * (`AGENT_RUNNER_TOOL_SANDBOX` — Docker by default) and hands `runSession` a
 * sandbox factory. ass-server registers the tools from the bundle metadata and
 * dispatches each call into the sandbox, so a tool's code — and the secrets it
 * uses — never run in this worker process.
 *
 * `runSession` runs the entire agent loop in-process and returns a handle whose
 * `.done` resolves on completion, error, or abort. The per-turn `SessionExecutor`
 * contract collapses to one "turn" that drives the whole session — fine for v1
 * since we don't yet park sessions across runner restarts.
 */
export class AssServerExecutor implements SessionExecutor {
    constructor(private readonly options: AssServerExecutorOptions) {}

    async runTurn(input: ExecutorTurnInput): Promise<ExecutorTurnOutput> {
        const { job } = input
        if (!job.applicationId || !job.revisionId) {
            return {
                kind: 'failed',
                error: 'job missing applicationId or revisionId — cannot resolve a bundle',
            }
        }

        const revision = await this.options.repository.resolveByRevisionId(job.revisionId)
        if (!revision) {
            return { kind: 'failed', error: `revision ${job.revisionId} not found` }
        }
        if (revision.applicationId !== job.applicationId) {
            return {
                kind: 'failed',
                error: `revision ${job.revisionId} belongs to a different application than the job`,
            }
        }
        if (revision.revisionState !== 'ready') {
            return {
                kind: 'failed',
                error: `revision ${job.revisionId} is not ready (state=${revision.revisionState})`,
            }
        }

        let bundleBytes: Buffer
        try {
            bundleBytes = await this.options.bundleStore.downloadBundle(
                revision.bundleS3Key,
                revision.bundleSha256 || undefined
            )
        } catch (err) {
            logger.error('runner bundle download failed', {
                sessionId: job.sessionId,
                key: revision.bundleS3Key,
                error: String(err),
            })
            return { kind: 'failed', error: `bundle download failed: ${String(err)}` }
        }

        const extracted = await extractBundleToTempDir(bundleBytes)
        try {
            return await this.runWithBundle(input, revision, extracted.dir)
        } finally {
            await extracted.cleanup().catch((err) => {
                logger.error('runner bundle cleanup failed', {
                    sessionId: job.sessionId,
                    error: String(err),
                })
            })
        }
    }

    private async runWithBundle(
        input: ExecutorTurnInput,
        _revision: ResolvedRevision,
        bundleDir: string
    ): Promise<ExecutorTurnOutput> {
        // Deployed bundles are single-agent (one `.ass.yaml` per tarball, produced
        // by `ass build`). `loadCompiledAgent` reads that flat shape — different
        // from `loadProject`, which is for the dev `ass run` TS-source tree.
        const { project, agent } = await loadCompiledAgent(bundleDir)

        const triggerPayload = input.state.initialInput ?? null
        const sessionId = input.job.sessionId
        const sessionLogger = createSessionLogger({
            teamId: input.job.teamId,
            applicationId: input.job.applicationId,
            sessionId,
            producer: this.options.logProducer,
        })
        const bridge = new BusBridgingRegistry(this.options.bus, sessionId, sessionLogger)

        // `env` is the dict ass-server hands to user tools when resolving
        // their declared `secrets:` list — keep it scoped to the app's
        // decrypted env ONLY. Runner-process credentials (ANTHROPIC_API_KEY,
        // ENCRYPTION_SALT_KEYS, DB URLs) must never be reachable from here.
        // The Claude Agent SDK reads ANTHROPIC_API_KEY from process.env on
        // its own (child-process inheritance) — separate path, separate
        // trust boundary.
        logger.info(
            {
                sessionId,
                processHasAnthropicKey: Boolean(process.env.ANTHROPIC_API_KEY),
                appSecretKeys: Object.keys(input.job.secrets),
            },
            'invoking runSession'
        )
        let makeToolSandbox
        try {
            makeToolSandbox = makeToolSandboxFactory(agent, (line) => logger.debug({ sessionId, line }, 'tool-sandbox'))
        } catch (err) {
            return { kind: 'failed', error: `tool sandbox unavailable: ${String(err)}` }
        }

        const handle = runSession({
            project,
            agent,
            registry: bridge,
            sessionId,
            triggerPayload,
            env: input.job.secrets,
            makeToolSandbox,
            onLog: (line: string) => {
                logger.debug({ sessionId, line }, 'runSession')
                sessionLogger.appendLog({ level: 'INFO', message: line })
            },
        })

        // Watch the session's input channel for a `/cancel/:id` request. The
        // deployed runner drives the whole session inside this one call, so a
        // single subscription covers the run's entire lifetime.
        let cancelled = false
        const unsubscribe = await this.options.bus.subscribeInput(sessionId, (msg) => {
            if (msg.type === 'cancel') {
                cancelled = true
                logger.info({ sessionId }, 'cancel received — aborting run')
                handle.abort()
            }
        })
        try {
            await handle.done
        } finally {
            await unsubscribe().catch((err) => {
                logger.error('cancel-subscription cleanup failed', { sessionId, error: String(err) })
            })
        }

        if (cancelled) {
            return { kind: 'cancelled' }
        }
        if (bridge.lastError) {
            return { kind: 'failed', error: bridge.lastError }
        }
        return {
            kind: 'completed',
            message: {
                role: 'assistant',
                content: bridge.lastResult?.text ?? '',
                at: new Date().toISOString(),
            },
            output: bridge.lastResult ?? { ok: true },
        }
    }
}
