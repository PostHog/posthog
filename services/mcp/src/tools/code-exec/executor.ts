/**
 * Sandbox executor seam for the code-execution verbs, plus the local dev/test
 * implementation. `LocalVmExecutor` runs the agent script in a `node:vm`
 * context whose only importable module is a preconfigured `@posthog/sdk` bound
 * to the plan/enforce transport fetch — scripts can never escape the transport,
 * because `createClient` is wrapped to force-override `fetch`, `host`, and
 * `apiKey` no matter what the script passes.
 *
 * `node:vm` is NOT a security boundary; this executor exists for development
 * and tests only and refuses to construct anywhere else (spec §3.3/§3.4 — the
 * production substrate is the Modal sandbox pool, a follow-up).
 */

import vm from 'node:vm'

import * as sdk from '@posthog/sdk'
import type { CreateClientOptions } from '@posthog/sdk'

import type { FetchLike } from '@/lib/code-exec'
import { env } from '@/lib/env'

export interface SandboxExecutionRequest {
    /** Original TypeScript source (compiled here when `compiledJs` is absent). */
    source: string
    /** Pre-compiled CJS, when the caller already ran the transform. */
    compiledJs?: string
    /** Transport every SDK call must flow through (plan or enforce mode). */
    transportFetch: FetchLike
    timeoutMs: number
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
            'The local VM executor is development/test-only — production code execution requires the Modal sandbox pool (not wired up yet).'
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
 * Rewrite the agent's ES module into a CJS-shaped script:
 *
 *   - `import` declarations become `require(...)` destructurings (served only
 *     by the sandbox's require shim);
 *   - `export default <expr>` becomes `module.exports.default = <expr>`;
 *   - everything else — including top-level `await` — is wrapped in one async
 *     IIFE stored on `module.exports.__run`, awaited by the executor.
 *
 * This is what makes top-level await work: esbuild refuses to emit CJS from a
 * module with top-level await, so the module syntax is lowered here (via the
 * TypeScript AST, statement text preserved verbatim) before esbuild only has
 * to strip types.
 */
export async function rewriteModuleToCjs(source: string): Promise<string> {
    // Lazy for the same reason as the compile gate: typescript is heavy and
    // only the code-execution path needs it.
    const ts = (await import('typescript')).default
    const sourceFile = ts.createSourceFile('script.ts', source, ts.ScriptTarget.ES2022, true)

    const requires: string[] = []
    const body: string[] = []

    for (const statement of sourceFile.statements) {
        if (ts.isImportDeclaration(statement)) {
            if (!ts.isStringLiteral(statement.moduleSpecifier)) {
                continue
            }
            const specifier = JSON.stringify(statement.moduleSpecifier.text)
            const clause = statement.importClause
            if (!clause || clause.isTypeOnly) {
                continue
            }
            if (clause.name) {
                requires.push(`const ${clause.name.text} = require(${specifier}).default;`)
            }
            if (clause.namedBindings) {
                if (ts.isNamespaceImport(clause.namedBindings)) {
                    requires.push(`const ${clause.namedBindings.name.text} = require(${specifier});`)
                } else {
                    const named = clause.namedBindings.elements
                        .filter((element) => !element.isTypeOnly)
                        .map((element) =>
                            element.propertyName
                                ? `${element.propertyName.text}: ${element.name.text}`
                                : element.name.text
                        )
                    if (named.length > 0) {
                        requires.push(`const { ${named.join(', ')} } = require(${specifier});`)
                    }
                }
            }
            continue
        }

        if (ts.isExportAssignment(statement) && !statement.isExportEquals) {
            body.push(`module.exports.default = ${statement.expression.getText(sourceFile)};`)
            continue
        }

        const modifiers = ts.canHaveModifiers(statement) ? ts.getModifiers(statement) : undefined
        const hasExport = modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) === true
        const hasDefault = modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword) === true
        const statementText = source.slice(statement.getStart(sourceFile), statement.end)

        if (hasExport && hasDefault) {
            // `export default function f() {}` / `export default class C {}` —
            // stripping the modifiers leaves a valid function/class expression.
            body.push(`module.exports.default = ${statementText.replace(/^export\s+default\s+/, '')};`)
            continue
        }
        if (hasExport) {
            // Named exports carry no contract; keep the declaration, drop the keyword.
            body.push(statementText.replace(/^export\s+/, ''))
            continue
        }
        body.push(statementText)
    }

    return `${requires.join('\n')}\nmodule.exports.__run = (async () => {\n${body.join('\n')}\n})();`
}

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

export class LocalVmExecutor implements SandboxExecutor {
    constructor() {
        // Fail-closed allowlist, mirroring `resolveFeatureFlagOverrides`: an
        // unset NODE_ENV must not unlock local execution.
        if (env.NODE_ENV !== 'development' && env.NODE_ENV !== 'test') {
            throw new SandboxUnavailableError()
        }
    }

    async execute(request: SandboxExecutionRequest): Promise<SandboxExecutionResult> {
        const consoleOutput: string[] = []
        try {
            const compiledJs = request.compiledJs ?? (await this.compile(request.source))

            // `createClient` force-overrides transport/host/key so a script that
            // passes its own `fetch` or `host` still cannot leave the transport.
            const createClient = (options: CreateClientOptions = {}): sdk.PostHogClient =>
                sdk.createClient({
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

    private async compile(source: string): Promise<string> {
        const cjsShaped = await rewriteModuleToCjs(source)
        // Lazy like `typescript` above: esbuild is external to the Hono bundle
        // (its API locates the binary via __filename, so it cannot be inlined)
        // and only the dev/test execution path may load it.
        const { transform } = await import('esbuild')
        // Only type stripping remains — the module syntax is already lowered.
        const result = await transform(cjsShaped, { loader: 'ts', format: 'cjs', target: 'es2022' })
        return result.code
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
