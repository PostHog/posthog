/**
 * Compile every `kind: "custom"` tool's `source.ts` into `compiled.js` and
 * write the result into the bundle. Called at freeze time, after validate
 * has passed (so we know each source exists + parses).
 *
 * Design: authors only ever write `source.ts`. `compiled.js` is a build
 * artifact owned by the janitor. The runner / sandbox loads `compiled.js`
 * exactly as it always did — only the producer changed.
 *
 * Why freeze and not validate:
 *   - Validate is pure (no bundle writes) and is called many times during
 *     authoring; compiling N times per draft iteration is wasteful.
 *   - Freeze already mutates the bundle (writes the `.frozen` marker,
 *     stamps sha256). Compile fits semantically — it's a build step.
 *   - The compile + freeze pair is the contract: "once frozen, the
 *     compiled.js you'll find in this bundle is what the runner runs."
 *
 * On any source failing to transform we abort the whole freeze and bubble a
 * structured error back. Partial bundles (some tools compiled, some not)
 * would leave a broken revision that validate-pass would re-accept on the
 * next freeze attempt — fail fast instead.
 */

import { transform as esbuildTransform } from 'esbuild'
import * as vm from 'vm'

import { AgentRevision, BundleStore } from '@posthog/agent-shared'

export interface CompileCustomToolsError {
    /** Tool id from `spec.tools[].id`. */
    tool_id: string
    /** Bundle-relative source path that failed to compile. */
    source_path: string
    /** Single-line error message from esbuild. */
    message: string
}

export interface CompileCustomToolsResult {
    /** Number of tools that were compiled and written. */
    compiled: number
    /** Per-tool errors. When non-empty, the caller MUST abort the freeze —
     *  any compiled.js we did write is now incoherent with at least one
     *  failed tool, and the next validate would re-pass against the
     *  partial state. */
    errors: CompileCustomToolsError[]
}

export async function compileCustomToolsIntoBundle(
    rev: AgentRevision,
    bundle: BundleStore
): Promise<CompileCustomToolsResult> {
    const errors: CompileCustomToolsError[] = []
    let compiled = 0
    for (const tool of rev.spec.tools) {
        if (tool.kind !== 'custom') {
            continue
        }
        const base = tool.path.replace(/\/$/, '')
        const sourcePath = `${base}/source.ts`
        const compiledPath = `${base}/compiled.js`
        try {
            const source = await bundle.readText(rev.id, sourcePath)
            // CJS so the existing sandbox loader (`vm.runInContext` /
            // `node host`) keeps working — no module-system change needed.
            // `inline` source maps would bloat the bundle without giving us
            // a useful debug surface (the runner doesn't expose them);
            // omit them for now.
            const out = await esbuildTransform(source, {
                loader: 'ts',
                format: 'cjs',
                target: 'node20',
            })
            // Shape check: a syntactically-valid source.ts can still produce
            // a compiled.js the runner can't dispatch — e.g.
            // `export default async function run() {}` parses fine but
            // exports a bare function, and the runner's loader requires
            // `{actions: {default: fn}}`. We catch that here so the failure
            // surfaces at freeze (recoverable, no live agent yet) instead
            // of at the first session invocation (live, opaque, mid-chat).
            const shapeErr = validateCompiledShape(tool.id, out.code)
            if (shapeErr) {
                errors.push({ tool_id: tool.id, source_path: sourcePath, message: shapeErr })
                continue
            }
            await bundle.write(rev.id, compiledPath, out.code)
            compiled += 1
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err)
            errors.push({
                tool_id: tool.id,
                source_path: sourcePath,
                message: message.split('\n')[0],
            })
        }
    }
    return { compiled, errors }
}

/**
 * Eval the compiled.js in a minimal vm context and confirm it exports the
 * exact shape the runner's sandbox loader expects:
 *   `{ id?, actions: { default: fn | { run: fn }, ... } }`
 *
 * We mirror the runner's CJS extraction (`module.exports.default ?? module.exports`)
 * so the check passes/fails identically. Returns null on success or a single-
 * line explanation on failure — kept terse because it gets surfaced verbatim
 * to the author.
 *
 * Why `actions.default` specifically: the runner's dispatcher
 * (`build-agent-tools.ts:makeCustomTool`) always invokes with `action: 'default'`.
 * A tool that ships without `actions.default` will load but never dispatch.
 */
function validateCompiledShape(toolId: string, code: string): string | null {
    const sandbox: Record<string, unknown> = {
        module: { exports: {} },
        exports: {},
        console: { log: () => undefined, warn: () => undefined, error: () => undefined },
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
        Promise,
        URL,
        URLSearchParams,
        TextEncoder,
        TextDecoder,
        Buffer,
        JSON,
    }
    sandbox.global = sandbox
    const ctx = vm.createContext(sandbox)
    try {
        vm.runInContext(code, ctx, { filename: `tools/${toolId}/compiled.js`, timeout: 1000 })
    } catch (err) {
        return `compiled output threw at module load: ${(err as Error).message.split('\n')[0]}`
    }
    const moduleExports = (sandbox.module as { exports: unknown }).exports
    const exported = (moduleExports as { default?: unknown })?.default ?? moduleExports
    if (!exported || typeof exported !== 'object') {
        return 'source.ts must export `{ id?, actions: { default: fn } }` — got a non-object (likely `export default <function>` instead of `export default { actions: { default: fn } }`)'
    }
    const obj = exported as { actions?: unknown }
    if (!obj.actions || typeof obj.actions !== 'object') {
        return 'source.ts must export `{ actions: { default: fn } }` — `actions` is missing or not an object'
    }
    const actions = obj.actions as Record<string, unknown>
    const def = actions.default
    const isCallable = typeof def === 'function'
    const isRunWrapper = def && typeof def === 'object' && typeof (def as { run?: unknown }).run === 'function'
    if (!isCallable && !isRunWrapper) {
        const got = def === undefined ? 'undefined' : typeof def
        return `source.ts must export \`actions.default\` as a function (or \`{ run: fn }\`) — got ${got}. The runner always dispatches action="default"; other action names will load but never fire.`
    }
    return null
}
