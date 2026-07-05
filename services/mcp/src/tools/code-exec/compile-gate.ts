/**
 * Compile gate for `exec run` / `exec apply`: typechecks an agent script
 * against the pinned `@posthog/sdk` declarations before any execution, plus
 * two contract lints (the script must `export default`, and must not call
 * `require(` — imports are the only sanctioned module syntax).
 *
 * Implementation: an in-memory `ts.LanguageService` whose virtual file system
 * holds the script and the bundled SDK `.d.ts` (from the generated `SDK_DTS`
 * artifact). Standard lib files are resolved from the installed `typescript`
 * package on disk via `ts.getDefaultLibFilePath` + `ts.sys` — that works under
 * vitest, tsx dev, and the Node runtime; the production Hono bundle never runs
 * the gate because the local sandbox executor refuses to construct outside
 * development/test (spec §3.3/§3.4 — the production substrate is the Modal
 * sandbox pool, a follow-up). The language service is cached at module level,
 * so warm checks only pay for re-checking the script file.
 */

import type ts from 'typescript'

export interface CompileDiagnostic {
    /** 1-based line in the submitted script. */
    line: number
    /** 1-based column in the submitted script. */
    character: number
    message: string
    /** TS diagnostic code; contract lints use the reserved 90xxx range. */
    code: number
}

export type CompileGateResult = { ok: true } | { ok: false; diagnostics: CompileDiagnostic[] }

export const MISSING_EXPORT_DEFAULT_CODE = 90001
export const REQUIRE_FORBIDDEN_CODE = 90002

const SCRIPT_PATH = '/script.ts'
const SANDBOX_GLOBALS_PATH = '/sandbox-globals.d.ts'
const SDK_VIRTUAL_ROOT = '/node_modules/@posthog/sdk/'

/**
 * Globals the sandbox actually injects (executor.ts) beyond the ES2022 lib —
 * declared here so scripts typecheck against exactly what they will get, with
 * neither the DOM lib nor @types/node in scope.
 */
const SANDBOX_GLOBALS_DTS = `
interface SandboxConsole {
    log(...args: unknown[]): void
    info(...args: unknown[]): void
    warn(...args: unknown[]): void
    error(...args: unknown[]): void
    debug(...args: unknown[]): void
}
declare var console: SandboxConsole
declare function setTimeout(handler: (...args: unknown[]) => void, timeout?: number): number
declare function clearTimeout(handle?: number): void
`

interface GateService {
    ts: typeof import('typescript')
    service: ts.LanguageService
    setScript: (source: string) => void
}

let cachedGate: GateService | null = null

async function getGateService(): Promise<GateService> {
    if (cachedGate) {
        return cachedGate
    }
    // Lazy: `typescript` (~8 MB) and the bundled SDK declarations (~4 MB) stay
    // off the import path of everything that doesn't run the gate.
    const tsModule = (await import('typescript')).default
    const { SDK_DTS } = await import('@/generated/code-exec/sdk-dts')

    const virtualFiles = new Map<string, string>()
    for (const [relativePath, contents] of Object.entries(SDK_DTS)) {
        virtualFiles.set(`${SDK_VIRTUAL_ROOT}${relativePath}`, contents)
    }
    virtualFiles.set(SANDBOX_GLOBALS_PATH, SANDBOX_GLOBALS_DTS)

    let scriptSource = ''
    let scriptVersion = 0

    const compilerOptions: ts.CompilerOptions = {
        strict: true,
        target: tsModule.ScriptTarget.ES2022,
        module: tsModule.ModuleKind.ESNext,
        moduleResolution: tsModule.ModuleResolutionKind.Bundler,
        lib: ['lib.es2022.d.ts'],
        types: [],
        noEmit: true,
        // The SDK declarations are generated and megabytes long — checking them
        // on every script would dominate the gate's latency for zero signal.
        skipLibCheck: true,
        baseUrl: '/',
        // Deterministic resolution: the only importable module maps straight to
        // its virtual declaration file, no node_modules directory walking.
        paths: { '@posthog/sdk': [`${SDK_VIRTUAL_ROOT}index.d.ts`] },
    }

    const readVirtualOrDisk = (fileName: string): string | undefined => {
        if (fileName === SCRIPT_PATH) {
            return scriptSource
        }
        return virtualFiles.get(fileName) ?? tsModule.sys.readFile(fileName)
    }

    const host: ts.LanguageServiceHost = {
        getCompilationSettings: () => compilerOptions,
        getScriptFileNames: () => [SCRIPT_PATH, SANDBOX_GLOBALS_PATH],
        getScriptVersion: (fileName) => (fileName === SCRIPT_PATH ? String(scriptVersion) : '1'),
        getScriptSnapshot: (fileName) => {
            const contents = readVirtualOrDisk(fileName)
            return contents === undefined ? undefined : tsModule.ScriptSnapshot.fromString(contents)
        },
        getCurrentDirectory: () => '/',
        getDefaultLibFileName: (options) => tsModule.getDefaultLibFilePath(options),
        fileExists: (fileName) =>
            fileName === SCRIPT_PATH || virtualFiles.has(fileName) || tsModule.sys.fileExists(fileName),
        readFile: readVirtualOrDisk,
        directoryExists: (directoryName) => {
            if (directoryName === '/' || `${SDK_VIRTUAL_ROOT}index.d.ts`.startsWith(`${directoryName}/`)) {
                return true
            }
            return tsModule.sys.directoryExists(directoryName)
        },
        getDirectories: (directoryName) => tsModule.sys.getDirectories?.(directoryName) ?? [],
    }

    const service = tsModule.createLanguageService(host, tsModule.createDocumentRegistry())
    cachedGate = {
        ts: tsModule,
        service,
        setScript: (source: string) => {
            scriptSource = source
            scriptVersion += 1
        },
    }
    return cachedGate
}

function toDiagnostic(tsModule: typeof ts, diagnostic: ts.Diagnostic): CompileDiagnostic {
    const message = tsModule.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
    if (diagnostic.file && diagnostic.start !== undefined) {
        const { line, character } = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start)
        return { line: line + 1, character: character + 1, message, code: diagnostic.code }
    }
    return { line: 1, character: 1, message, code: diagnostic.code }
}

function positionOf(source: string, offset: number): { line: number; character: number } {
    const before = source.slice(0, offset)
    const line = before.split('\n').length
    const lastNewline = before.lastIndexOf('\n')
    return { line, character: offset - lastNewline }
}

function hasExportDefault(tsModule: typeof ts, sourceFile: ts.SourceFile): boolean {
    return sourceFile.statements.some((statement) => {
        if (tsModule.isExportAssignment(statement) && !statement.isExportEquals) {
            return true
        }
        const modifiers = tsModule.canHaveModifiers(statement) ? tsModule.getModifiers(statement) : undefined
        return (
            modifiers?.some((modifier) => modifier.kind === tsModule.SyntaxKind.DefaultKeyword) === true &&
            modifiers?.some((modifier) => modifier.kind === tsModule.SyntaxKind.ExportKeyword) === true
        )
    })
}

/**
 * Typecheck `source` and apply the contract lints. Returns `{ ok: true }` or
 * every diagnostic found, each anchored to a script line/column.
 */
export async function checkScript(source: string): Promise<CompileGateResult> {
    const gate = await getGateService()
    gate.setScript(source)

    const diagnostics: CompileDiagnostic[] = [
        ...gate.service.getSyntacticDiagnostics(SCRIPT_PATH),
        ...gate.service.getSemanticDiagnostics(SCRIPT_PATH),
    ].map((diagnostic) => toDiagnostic(gate.ts, diagnostic))

    const requireMatch = /\brequire\s*\(/.exec(source)
    if (requireMatch) {
        const { line, character } = positionOf(source, requireMatch.index)
        diagnostics.push({
            line,
            character,
            message: "require() is not available in scripts — use `import { client } from '@posthog/sdk'`.",
            code: REQUIRE_FORBIDDEN_CODE,
        })
    }

    const program = gate.service.getProgram()
    const sourceFile = program?.getSourceFile(SCRIPT_PATH)
    if (sourceFile && !hasExportDefault(gate.ts, sourceFile)) {
        diagnostics.push({
            line: 1,
            character: 1,
            message: 'Script must `export default` the value to return (e.g. `export default { updated }`).',
            code: MISSING_EXPORT_DEFAULT_CODE,
        })
    }

    return diagnostics.length === 0 ? { ok: true } : { ok: false, diagnostics }
}
