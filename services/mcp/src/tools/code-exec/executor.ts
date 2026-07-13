/**
 * Sandbox executor seam for the code-execution verbs, plus the local
 * implementation. `LocalVmExecutor` runs the agent script in a `node:vm`
 * context whose only importable module is a preconfigured `@posthog/sdk` bound
 * to the plan/enforce transport fetch — scripts can never escape the transport,
 * because `createClient` is wrapped to force-override `fetch`, `host`, and
 * `apiKey` no matter what the script passes.
 *
 * Scripts are lowered with sucrase (pure JS, inlined into every bundle — the
 * distributed CLI has no node_modules, so the toolchain cannot be
 * bundle-external; spec §4.8), with the CJS output wrapped in one async IIFE
 * so top-level await works against the vm `module`/`exports`/`require` shim.
 *
 * `node:vm` is NOT a security boundary; this executor refuses to construct
 * outside development/test unless `trustedLocal` is set — the explicit CLI
 * opt-in for the user's own machine (spec §4.8). The hosted production
 * substrate is the Modal sandbox pool, a follow-up (spec §3.3/§3.4).
 */

import vm from 'node:vm'
import { transform } from 'sucrase'

import * as sdk from '@posthog/sdk'
import type { CreateClientOptions } from '@posthog/sdk'

import type { FetchLike } from '@/lib/code-exec'

import { localVmExecutionSupported } from './availability'

export interface SandboxExecutionRequest {
    /** Original TypeScript source (compiled here when `compiledJs` is absent). */
    source: string
    /** Pre-compiled CJS, when the caller already ran the transform. */
    compiledJs?: string
    /** Transport every SDK call must flow through (plan or enforce mode). */
    transportFetch: FetchLike
    timeoutMs: number
    /**
     * Session-scoped default project/org for the sandboxed client. Without
     * them the SDK falls back to `GET /api/users/@me/` (the user's web current
     * team), which can diverge from the MCP session's active project — the
     * same script would then target different projects depending on whether it
     * fast-paths (tool handlers read session state) or sandboxes.
     */
    projectId?: string
    organizationId?: string
}

export interface SandboxExecutionResult {
    /** The script's resolved `export default` value. */
    output: unknown
    consoleOutput: string[]
    error?: { message: string }
}

export interface SandboxExecutor {
    execute(request: SandboxExecutionRequest): Promise<SandboxExecutionResult>
}

export class SandboxUnavailableError extends Error {
    constructor() {
        super(
            'The local VM executor only runs in development/test or with an explicit trusted-local opt-in — hosted production code execution requires the Modal sandbox pool (not wired up yet).'
        )
        this.name = 'SandboxUnavailableError'
    }
}

/** Placeholder credentials — the wrapped transport ignores both (see module doc). */
const SANDBOX_API_KEY = 'code-exec-plan'
const SANDBOX_HOST = 'https://sandbox.invalid'

/** Cap on captured console output so a logging loop cannot flood the response. */
const MAX_CONSOLE_CHARS = 20_000

/**
 * Extract an error message across realms: an `Error` thrown inside the vm
 * context is an instance of the vm realm's constructor, so `instanceof Error`
 * alone would stringify it as `Error: …` instead of reading `.message`.
 */
function errorMessage(error: unknown): string {
    if (error instanceof Error) {
        return error.message
    }
    if (typeof error === 'object' && error !== null && 'message' in error) {
        const message = (error as { message: unknown }).message
        if (typeof message === 'string') {
            return message
        }
    }
    return String(error)
}

function formatConsoleArg(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    if (value instanceof Error) {
        return value.message
    }
    try {
        return JSON.stringify(value) ?? String(value)
    } catch {
        return String(value)
    }
}

function createCapturedConsole(lines: string[]): Pick<Console, 'log' | 'info' | 'warn' | 'error' | 'debug'> {
    let capturedChars = 0
    let truncated = false
    const capture =
        (level: string) =>
        (...args: unknown[]): void => {
            if (truncated) {
                return
            }
            const line = `[${level}] ${args.map(formatConsoleArg).join(' ')}`
            capturedChars += line.length
            if (capturedChars > MAX_CONSOLE_CHARS) {
                truncated = true
                lines.push('[console output truncated]')
                return
            }
            lines.push(line)
        }
    return {
        log: capture('log'),
        info: capture('info'),
        warn: capture('warn'),
        error: capture('error'),
        debug: capture('debug'),
    }
}

export interface LocalVmExecutorOptions {
    /**
     * Explicit opt-in for the user's own machine (spec §4.8): only the CLI
     * entrypoint may set it — never derive it from env, or the production
     * server could accidentally unlock local execution.
     */
    trustedLocal?: boolean
}

export class LocalVmExecutor implements SandboxExecutor {
    constructor(options: LocalVmExecutorOptions = {}) {
        // Shared probe (`availability.ts`) so the instructions builder and this
        // fail-closed check can never disagree about where scripts may run.
        if (!options.trustedLocal && !localVmExecutionSupported()) {
            throw new SandboxUnavailableError()
        }
    }

    async execute(request: SandboxExecutionRequest): Promise<SandboxExecutionResult> {
        const consoleOutput: string[] = []
        try {
            const compiledJs = request.compiledJs ?? this.compile(request.source)

            // `createClient` force-overrides transport/host/key so a script that
            // passes its own `fetch` or `host` still cannot leave the transport.
            // The session project/org ride along as defaults (a script may still
            // scope a call explicitly) so implicit scoping matches the fast path.
            const createClient = (options: CreateClientOptions = {}): sdk.PostHogClient =>
                sdk.createClient({
                    ...(request.projectId !== undefined ? { projectId: request.projectId } : {}),
                    ...(request.organizationId !== undefined ? { organizationId: request.organizationId } : {}),
                    ...options,
                    apiKey: SANDBOX_API_KEY,
                    host: SANDBOX_HOST,
                    fetch: request.transportFetch,
                })
            const sdkModule = { ...sdk, createClient, client: createClient() }

            const requireShim = (specifier: string): unknown => {
                if (specifier === '@posthog/sdk') {
                    return sdkModule
                }
                throw new Error(
                    `Module "${specifier}" is not available in the code-execution sandbox — only "@posthog/sdk" can be imported.`
                )
            }

            const moduleShim: { exports: Record<string, unknown> } = { exports: {} }
            const sandbox = {
                module: moduleShim,
                exports: moduleShim.exports,
                require: requireShim,
                console: createCapturedConsole(consoleOutput),
                URL,
                URLSearchParams,
                TextEncoder,
                TextDecoder,
                setTimeout,
                clearTimeout,
            }
            const context = vm.createContext(sandbox)

            // The vm `timeout` option only bounds the synchronous top of the
            // script (e.g. a tight `while` loop); the async continuation is
            // bounded by the race below. On race timeout the vm promise keeps
            // running in the background — acceptable for a dev/test executor.
            new vm.Script(compiledJs, { filename: 'script.js' }).runInContext(context, {
                timeout: request.timeoutMs,
            })

            await this.withTimeout(Promise.resolve(moduleShim.exports.__run), request.timeoutMs)

            const exported = moduleShim.exports.default
            const output = typeof exported === 'function' ? await (exported as () => unknown)() : await exported
            return { output, consoleOutput }
        } catch (error) {
            return { output: undefined, consoleOutput, error: { message: errorMessage(error) } }
        }
    }

    /**
     * Lower TS + ES module syntax to CJS served by the require shim, then wrap
     * everything in one async IIFE on `module.exports.__run` — `execute` awaits
     * it before reading `exports.default`, which is what makes top-level await
     * work in a CJS-shaped script. `disableESTransforms` keeps modern syntax
     * (optional chaining, class fields) verbatim — the runtime is node ≥ 22.
     */
    private compile(source: string): string {
        const { code } = transform(source, { transforms: ['typescript', 'imports'], disableESTransforms: true })
        return `module.exports.__run = (async () => {\n${code}\n})();`
    }

    private async withTimeout(promise: Promise<unknown>, timeoutMs: number): Promise<void> {
        let timer: ReturnType<typeof setTimeout> | undefined
        try {
            await Promise.race([
                promise,
                new Promise((_resolve, reject) => {
                    timer = setTimeout(
                        () => reject(new Error(`Script execution timed out after ${timeoutMs}ms`)),
                        timeoutMs
                    )
                }),
            ])
        } finally {
            clearTimeout(timer)
        }
    }
}
