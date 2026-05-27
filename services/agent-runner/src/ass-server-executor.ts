import { loadCompiledAgent } from '@repo/ass-server/load-compiled-agent'
import { runSession } from '@repo/ass-server/session-runner'

import {
    ApplicationsRepository,
    BundleStore,
    LogProducer,
    ResolvedRevision,
    SandboxInstancesRepository,
    SessionBus,
    createSessionLogger,
    extractBundleToTempDir,
    logger,
    withTiming,
} from '@posthog/agent-core'

import { BusBridgingRegistry } from './ass-server-bridge'
import { ExecutorTurnInput, ExecutorTurnOutput, SessionExecutor } from './executor'
import { makeToolSandboxFactory } from './tool-sandbox'

export interface AssServerExecutorOptions {
    bundleStore: BundleStore
    repository: ApplicationsRepository
    /**
     * Optional durable lifecycle tracker for sandbox containers/processes.
     * When present, every acquired sandbox writes an AgentApplicationSandboxInstance
     * row the janitor can reap if the worker dies mid-session. Omit in tests.
     */
    sandboxInstances?: SandboxInstancesRepository
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
            bundleBytes = await withTiming(
                { op: 'bundle.download', sessionId: job.sessionId, key: revision.bundleS3Key },
                () => this.options.bundleStore.downloadBundle(revision.bundleS3Key, revision.bundleSha256 || undefined)
            )
        } catch (err) {
            logger.error('runner bundle download failed', {
                sessionId: job.sessionId,
                key: revision.bundleS3Key,
                error: String(err),
            })
            return { kind: 'failed', error: `bundle download failed: ${String(err)}` }
        }

        const extracted = await withTiming({ op: 'bundle.extract', sessionId: job.sessionId }, () =>
            extractBundleToTempDir(bundleBytes)
        )
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
        revision: ResolvedRevision,
        bundleDir: string
    ): Promise<ExecutorTurnOutput> {
        // Deployed bundles are single-agent (one `.ass.yaml` per tarball, produced
        // by `ass build`). `loadCompiledAgent` reads that flat shape — different
        // from `loadProject`, which is for the dev `ass run` TS-source tree.
        // Cheap (JSON + small tar untar) — not wrapped in withTiming so
        // we don't have to drag the LoadedCompiledAgent type through a
        // generic boundary that the workspace re-exports don't carry.
        const { project, agent } = await loadCompiledAgent(bundleDir)

        const triggerPayload = input.state.initialInput ?? null
        const sessionId = input.job.sessionId
        const isFirstTurn = input.state.turnCount === 0
        // Latest user message — the worker pushed initialInput and any
        // drained `/send` messages onto state.messages BEFORE calling
        // runTurn, so the last user-role entry is what the model should
        // respond to this turn. Fall back to the trigger payload as a
        // string if nothing was pushed (defensive: shouldn't happen in
        // normal flows).
        const userPrompt = lastUserMessage(input.state.messages) ?? safeJsonStringify(triggerPayload)
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
            makeToolSandbox = makeToolSandboxFactory(
                agent,
                (line) => logger.debug({ sessionId, line }, 'tool-sandbox'),
                this.options.sandboxInstances
                    ? {
                          repo: this.options.sandboxInstances,
                          attribution: {
                              teamId: revision.teamId,
                              applicationId: revision.applicationId,
                              revisionId: revision.revisionId,
                          },
                      }
                    : undefined
            )
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
            // Threaded so the sandbox container is labelled `ass.revision=<id>`,
            // making it attributable to a deploy in `docker ps` / orphan reaping.
            revisionId: revision.revisionId,
            // Turn-by-turn mode: ask_for_input ends the SDK turn via
            // q.interrupt() and the worker parks the queue row, instead
            // of suspending on an in-process Promise that handle.send
            // would resolve. The whole-session model only fits ass run.
            turnByTurn: true,
            // First turn: pass `opts.sessionId` to the SDK as the new
            // session UUID (matching `agent_sessions.id`). Subsequent
            // turns: pass `resume: <same id>` so the SDK rehydrates the
            // conversation from its session store. ~/.claude on the
            // host disk today; pluggable SessionStore lands later.
            previousSessionId: isFirstTurn ? undefined : sessionId,
            // The new user message for THIS turn — the worker stamped
            // it into state.messages from the trigger payload (turn 0)
            // or the drained `/send` (turn N+1).
            userPrompt,
            onLog: (line: string) => {
                logger.debug({ sessionId, line }, 'runSession')
                sessionLogger.appendLog({ level: 'INFO', message: line })
            },
        })

        // /cancel arrives via the bus and fires the SDK's abort
        // controller — same path on a running turn. `user_message`
        // delivery via the bus is gone: in turn-by-turn mode there's
        // never an `ask_for_input` waiter to resolve, the durable
        // pending_inputs column is the path. The bus subscription
        // here is now just for cancel.
        let cancelled = false
        const unsubscribe = await this.options.bus.subscribeInput(sessionId, (msg) => {
            if (msg.type === 'cancel') {
                cancelled = true
                logger.info({ sessionId }, 'cancel received — aborting turn')
                handle.abort()
                return
            }
            // `user_message` arrivals during a running turn just get
            // queued in pending_inputs by the ingress and drained on
            // the NEXT runTurn call. Nothing to do here.
        })
        try {
            // `handle.done` resolves when the SDK turn ends — either
            // the model produced its final assistant message + no more
            // tool calls, the agent called ask_for_input (interrupted
            // in turnByTurn mode), or end_session fired.
            await withTiming({ op: 'runtime.turn', sessionId, agent: agent.slug }, () => handle.done)
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
        // Built the per-turn assistant message from the bridge's last
        // captured text result. Empty string is valid (a turn that's
        // pure tool calls with no assistant text — unusual but legal).
        const message = {
            role: 'assistant' as const,
            content: bridge.lastResult?.text ?? '',
            at: new Date().toISOString(),
        }
        // `end_session` was the agent's explicit signal to terminate.
        // Without it, the SDK turn ended naturally and we have more
        // turns to come — park awaiting the next `/send`.
        if (bridge.endRequested) {
            return {
                kind: 'completed',
                message,
                output: bridge.lastResult ?? { ok: true },
            }
        }
        return {
            kind: 'awaiting_input',
            message,
            reason: null,
        }
    }
}

/** Walk `state.messages` tail-first; return the latest user-role content or null. */
function lastUserMessage(messages: ReadonlyArray<{ role: string; content: string }>): string | null {
    for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === 'user') {
            return messages[i].content
        }
    }
    return null
}

/** JSON-stringify, but return a safe fallback on circular / non-serialisable inputs. */
function safeJsonStringify(value: unknown): string {
    try {
        return JSON.stringify(value ?? null) ?? 'null'
    } catch {
        return 'null'
    }
}
