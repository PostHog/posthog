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
