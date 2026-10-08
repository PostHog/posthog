import { newQuickJSWASMModuleFromVariant, shouldInterruptAfterDeadline } from 'quickjs-emscripten-core'
import type { QuickJSContext, QuickJSDeferredPromise, QuickJSHandle, QuickJSWASMModule } from 'quickjs-emscripten-core'
import { z } from 'zod'

import { TOKEN_CHAR_LIMIT } from './schema-utils'

export const RUN_CODE_TOOL_NAME = 'run_code'

export const CODE_RUN_LIMITS = {
    timeoutMs: 60_000,
    memoryBytes: 64 * 1024 * 1024,
    maxStackBytes: 1024 * 1024,
    maxCalls: 50,
    maxConcurrentHostCalls: 4,
}

export type CodeRunLimits = typeof CODE_RUN_LIMITS

const MAX_OUTPUT_CHARS = TOKEN_CHAR_LIMIT
const MAX_LOG_CHARS = MAX_OUTPUT_CHARS / 4

export const RUN_CODE_TOOL_DESCRIPTION = `Run a JavaScript script that orchestrates PostHog tools. The script is the body of an async function: use await, loops and Promise.all, then return a JSON-serializable value. Only the returned value, console output and the number of calls come back, so filter and aggregate large results inside the script.

- await posthog.search(query): find tools by keywords, ranked by relevance.
- await posthog.schema(toolName): a tool's description and input schema.
- await posthog.call(toolName, args): run a tool and get its parsed result. Throws if the tool fails.
- await posthog.exec(command): run any exec command (for example \`learn -s "funnel conversion"\`) and get its output. The exec guidance below applies inside scripts through this function and the helpers above.
- console.log(...values): add a note to the output.

The script has no network, filesystem or timers. Each run is limited to ${CODE_RUN_LIMITS.timeoutMs / 1000} seconds, ${CODE_RUN_LIMITS.maxCalls} posthog.call or posthog.exec invocations and ${CODE_RUN_LIMITS.maxConcurrentHostCalls} concurrent calls.

Example:
const flags = await posthog.call('feature-flag-get-all', { active: 'STALE' })
const stale = flags.results.filter((flag) => !flag.key.startsWith('test-'))
console.log(\`\${stale.length} of \${flags.results.length} stale flags kept\`)
return stale.map((flag) => ({ id: flag.id, key: flag.key }))`

export const runCodeSchema = z.object({
    code: z.string().min(1).describe('The body of an async JavaScript function. Return the value to send back.'),
})

/** What a script can reach. Every value crossing it is plain JSON. */
export interface CodeRunHost {
    search(query: string): Promise<unknown>
    schema(toolName: string): Promise<unknown>
    call(toolName: string, args: unknown): Promise<unknown>
    exec(command: string): Promise<unknown>
}

/** A guest-facing result: JSON text on success, a message on failure. */
type Settlement = { json: string } | { error: string }

export type CodeRunOutcome = { calls: number; logs: string[] } & (
    | { ok: true; result: unknown }
    | { ok: false; error: string }
)

// The guest sees `posthog` and `console` only. The host bridge passes strings, so
// nothing but JSON crosses the boundary, and it is removed from the global scope
// before the script runs.
const GUEST_PRELUDE = `(() => {
    const host = globalThis.__host
    delete globalThis.__host
    const format = (value) => (typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value)))
    const log = (...values) => host.log(values.map(format).join(' '))
    globalThis.console = Object.freeze({ log, info: log, warn: log, error: log })
    globalThis.posthog = Object.freeze({
        search: async (query) => JSON.parse(await host.search(String(query))),
        schema: async (toolName) => JSON.parse(await host.schema(String(toolName))),
        call: async (toolName, args) => JSON.parse(await host.call(String(toolName), JSON.stringify(args ?? {}))),
        exec: async (command) => JSON.parse(await host.exec(String(command))),
    })
})()`

function wrapScript(code: string): string {
    return `(async () => {
const value = await (async () => {
${code}
})()
return JSON.stringify(value === undefined ? null : value)
})()`
}

// Each run gets its own WebAssembly instance. QuickJS can leak objects on
// out-of-memory paths and then fail its leak assertion on dispose, which aborts
// the instance. A per-run instance keeps that failure inside the run.
async function newQuickJSInstance(): Promise<QuickJSWASMModule> {
    const variant = await import('@jitl/quickjs-singlefile-mjs-release-sync')
    return newQuickJSWASMModuleFromVariant(variant.default)
}

/**
 * Admits at most `max` tasks at once. A finishing task hands its slot straight
 * to the next waiter, so a task that starts between the release and the
 * waiter's wake-up cannot push the count over `max`.
 */
function createSlotLimiter(max: number): <T>(task: () => Promise<T>) => Promise<T> {
    let active = 0
    const waiters: (() => void)[] = []
    return async (task) => {
        if (active < max) {
            active++
        } else {
            await new Promise<void>((resolve) => waiters.push(resolve))
        }
        try {
            return await task()
        } finally {
            const next = waiters.shift()
            if (next) {
                next()
            } else {
                active--
            }
        }
    }
}

function describeGuestError(vm: QuickJSContext, handle: QuickJSHandle): string {
    const dumped: unknown = vm.dump(handle)
    if (dumped && typeof dumped === 'object' && 'message' in dumped) {
        const { name, message } = dumped as { name?: unknown; message?: unknown }
        return name ? `${String(name)}: ${String(message)}` : String(message)
    }
    return typeof dumped === 'string' ? dumped : JSON.stringify(dumped)
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

/**
 * Runs `code` in a fresh QuickJS runtime that can only reach `host`. Guest
 * errors, timeouts and limit hits come back as a failed outcome, never as a throw.
 */
export async function runCode(
    code: string,
    host: CodeRunHost,
    limits: CodeRunLimits = CODE_RUN_LIMITS
): Promise<CodeRunOutcome> {
    const quickjs = await newQuickJSInstance()
    const deadline = Date.now() + limits.timeoutMs
    const runtime = quickjs.newRuntime()
    runtime.setMemoryLimit(limits.memoryBytes)
    runtime.setMaxStackSize(limits.maxStackBytes)
    // Stops a busy guest. A guest that waits on the host is stopped by the timer below.
    runtime.setInterruptHandler(shouldInterruptAfterDeadline(deadline))
    const vm = runtime.newContext()

    const logs: string[] = []
    let logChars = 0
    const timeoutMessage = `Timed out after ${limits.timeoutMs / 1000} seconds.`
    let calls = 0
    // Host calls still in flight. Teardown disposes them, and a call that
    // settles later finds itself gone and leaves the disposed context alone.
    const pending = new Set<QuickJSDeferredPromise>()
    const inSlot = createSlotLimiter(limits.maxConcurrentHostCalls)
    let abort: (message: string) => void = () => {}
    const aborted = new Promise<string>((resolve) => {
        abort = resolve
    })

    const runPendingJobs = (): void => {
        const result = runtime.executePendingJobs()
        if (result.error) {
            abort(describeGuestError(vm, result.error))
            result.error.dispose()
        }
    }

    const settle = (deferred: QuickJSDeferredPromise, outcome: Settlement): void => {
        if (!pending.delete(deferred)) {
            return
        }
        const handle = 'json' in outcome ? vm.newString(outcome.json) : vm.newError(outcome.error)
        if ('json' in outcome) {
            deferred.resolve(handle)
        } else {
            deferred.reject(handle)
        }
        handle.dispose()
        runPendingJobs()
    }

    const asyncHostFunction = (name: string, run: (...args: string[]) => Promise<unknown>): QuickJSHandle =>
        vm.newFunction(name, (...argHandles) => {
            const args = argHandles.map((handle) => vm.getString(handle))
            const deferred = vm.newPromise()
            pending.add(deferred)
            inSlot(() => run(...args)).then(
                (value) => settle(deferred, { json: JSON.stringify(value) ?? 'null' }),
                (error: unknown) => settle(deferred, { error: errorMessage(error) })
            )
            return deferred.handle
        })

    const counted = (run: () => Promise<unknown>): Promise<unknown> => {
        if (calls === limits.maxCalls) {
            const message = `Call limit reached: a run may make at most ${limits.maxCalls} posthog.call or posthog.exec invocations.`
            abort(message)
            return Promise.reject(new Error(message))
        }
        calls++
        return run()
    }

    const hostObject = vm.newObject()
    const hostFunctions: [string, QuickJSHandle][] = [
        [
            'log',
            vm.newFunction('log', (lineHandle) => {
                const line = vm.getString(lineHandle)
                if (logChars < MAX_LOG_CHARS) {
                    logChars += line.length
                    logs.push(logChars < MAX_LOG_CHARS ? line : '[console output truncated]')
                }
            }),
        ],
        ['search', asyncHostFunction('search', (query) => host.search(query))],
        ['schema', asyncHostFunction('schema', (toolName) => host.schema(toolName))],
        [
            'call',
            asyncHostFunction('call', (toolName, argsJson) => counted(() => host.call(toolName, JSON.parse(argsJson)))),
        ],
        ['exec', asyncHostFunction('exec', (command) => counted(() => host.exec(command)))],
    ]
    for (const [name, handle] of hostFunctions) {
        vm.setProp(hostObject, name, handle)
        handle.dispose()
    }
    vm.setProp(vm.global, '__host', hostObject)
    hostObject.dispose()

    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        const prelude = vm.evalCode(GUEST_PRELUDE)
        vm.unwrapResult(prelude).dispose()

        const evaluated = vm.evalCode(wrapScript(code), 'run_code.js')
        if (evaluated.error) {
            const error = Date.now() >= deadline ? timeoutMessage : describeGuestError(vm, evaluated.error)
            evaluated.error.dispose()
            return { ok: false, error, logs, calls }
        }
        const settled = vm.resolvePromise(evaluated.value)
        evaluated.value.dispose()
        runPendingJobs()

        const timedOut = new Promise<string>((resolve) => {
            timer = setTimeout(() => resolve(timeoutMessage), Math.max(0, deadline - Date.now()))
        })
        const outcome = await Promise.race<Settlement>([
            settled.then((result) => {
                if (result.error) {
                    const error = describeGuestError(vm, result.error)
                    result.error.dispose()
                    return { error }
                }
                const json = vm.getString(result.value)
                result.value.dispose()
                return { json }
            }),
            Promise.race([aborted, timedOut]).then((error) => ({ error })),
        ])
        if ('error' in outcome) {
            // The interrupt handler surfaces a deadline hit as a bare "interrupted" error.
            const error = Date.now() >= deadline ? timeoutMessage : outcome.error
            return { ok: false, error, logs, calls }
        }
        return { ok: true, result: JSON.parse(outcome.json), logs, calls }
    } catch (error) {
        return { ok: false, error: errorMessage(error), logs, calls }
    } finally {
        clearTimeout(timer)
        try {
            for (const deferred of pending) {
                deferred.dispose()
            }
            pending.clear()
            vm.dispose()
            runtime.dispose()
        } catch {
            // The outcome is already decided, and the aborted instance is dropped with this run.
        }
    }
}

/** The agent-facing text: JSON, with an oversized return value replaced by a bounded preview. */
export function formatCodeRunOutcome(outcome: CodeRunOutcome): string {
    const { calls, logs } = outcome
    const body = outcome.ok ? { result: outcome.result, logs, calls } : { error: outcome.error, logs, calls }
    const text = JSON.stringify(body)
    if (!outcome.ok || text.length <= MAX_OUTPUT_CHARS) {
        return text
    }
    const serialized = JSON.stringify(outcome.result)
    return JSON.stringify({
        result: {
            truncated: true,
            total_chars: serialized.length,
            preview: serialized.slice(0, MAX_OUTPUT_CHARS / 2),
            hint: 'The return value is too large. Filter or aggregate it inside the script.',
        },
        logs,
        calls,
    })
}
