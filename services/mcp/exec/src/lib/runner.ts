import { transpileSnippet } from './transpiler'
import { capJson } from './truncate'

export interface ExecInput {
    snippet: string
    timeoutMs?: number
    maxBytes?: number
}

export interface ExecResult {
    stdout: string
    stderr: string
    value: unknown
    truncated: boolean
    shapeHint?: string
    error?: { kind: 'syntax' | 'runtime' | 'http'; message: string; details?: unknown }
    durationMs: number
}

interface CapturingConsole {
    console: Console
    stdout(): string
    stderr(): string
}

const DEFAULT_TIMEOUT_MS = 15_000
const DEFAULT_MAX_BYTES = 8192

export class SnippetRunner {
    constructor(private readonly clientFactory: () => unknown) {}

    async run(input: ExecInput): Promise<ExecResult> {
        const start = Date.now()
        const cap = createCapturingConsole()

        let js: string
        try {
            js = transpileSnippet(input.snippet)
        } catch (e) {
            return this.fail('syntax', e, cap, start)
        }

        let fn: (...args: unknown[]) => Promise<unknown>
        try {
            // eslint-disable-next-line @typescript-eslint/no-implied-eval, no-new-func
            fn = new Function('client', 'console', `return (async () => { ${js} })()`) as (
                ...args: unknown[]
            ) => Promise<unknown>
        } catch (e) {
            return this.fail('syntax', e, cap, start)
        }

        const client = this.clientFactory()

        try {
            const value = await withTimeout(fn(client, cap.console), input.timeoutMs ?? DEFAULT_TIMEOUT_MS)
            const { display, truncated, shapeHint } = capJson(value, input.maxBytes ?? DEFAULT_MAX_BYTES)
            return {
                stdout: cap.stdout(),
                stderr: cap.stderr(),
                value: truncated ? display : value,
                truncated,
                shapeHint,
                durationMs: Date.now() - start,
            }
        } catch (e) {
            const kind = looksLikeHttp(e) ? 'http' : 'runtime'
            return this.fail(kind, e, cap, start)
        }
    }

    private fail(kind: 'syntax' | 'runtime' | 'http', e: unknown, cap: CapturingConsole, start: number): ExecResult {
        const err = e as Error & { status?: number; body?: unknown; url?: string }
        const details: Record<string, unknown> = {}
        if (typeof err?.status === 'number') {
            details.status = err.status
        }
        if (err?.body !== undefined) {
            details.body = err.body
        }
        if (err?.url) {
            details.url = err.url
        }
        return {
            stdout: cap.stdout(),
            stderr: cap.stderr(),
            value: undefined,
            truncated: false,
            error: {
                kind,
                message: err?.message ?? String(e),
                details: Object.keys(details).length > 0 ? details : undefined,
            },
            durationMs: Date.now() - start,
        }
    }
}

function looksLikeHttp(e: unknown): boolean {
    if (!e || typeof e !== 'object') {
        return false
    }
    const candidate = e as { kind?: unknown; status?: unknown; response?: { status?: unknown } }
    if (candidate.kind === 'http') {
        return true
    }
    if (typeof candidate.status === 'number') {
        return true
    }
    if (candidate.response && typeof candidate.response.status === 'number') {
        return true
    }
    return false
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const handle = setTimeout(() => {
            reject(new Error(`exec timed out after ${ms}ms`))
        }, ms)
        promise.then(
            (value) => {
                clearTimeout(handle)
                resolve(value)
            },
            (err) => {
                clearTimeout(handle)
                reject(err)
            }
        )
    })
}

function createCapturingConsole(): CapturingConsole {
    const stdoutLines: string[] = []
    const stderrLines: string[] = []

    const format = (args: unknown[]): string =>
        args
            .map((a) => {
                if (typeof a === 'string') {
                    return a
                }
                try {
                    return JSON.stringify(a)
                } catch {
                    return String(a)
                }
            })
            .join(' ')

    const console = {
        log: (...args: unknown[]): void => {
            stdoutLines.push(format(args))
        },
        info: (...args: unknown[]): void => {
            stdoutLines.push(format(args))
        },
        debug: (...args: unknown[]): void => {
            stdoutLines.push(format(args))
        },
        warn: (...args: unknown[]): void => {
            stderrLines.push(format(args))
        },
        error: (...args: unknown[]): void => {
            stderrLines.push(format(args))
        },
        trace: (...args: unknown[]): void => {
            stderrLines.push(format(args))
        },
    } as unknown as Console

    return {
        console,
        stdout: () => stdoutLines.join('\n'),
        stderr: () => stderrLines.join('\n'),
    }
}
