/**
 * Bundle audit for the MCP Cloudflare Worker.
 *
 * Drives `wrangler deploy --dry-run --metafile`, parses the resulting esbuild
 * metafile, and reports:
 *
 *   1. Total bundle size + input count
 *   2. Top-N individual modules by `bytesInOutput`
 *   3. Per-group totals (own code vs deps, with deps grouped by package)
 *   4. Per-folder totals for `src/generated/*` (one OpenAPI client per folder)
 *   5. Trace lookups for known-suspect dependencies (mime-db / mime-types,
 *      yaml, posthog-node, @posthog/mcp, zod dual v3/v4) — who pulls them in
 *
 * Run from services/mcp:
 *
 *   pnpm tsx scripts/audit-bundle.ts
 *     [--outdir /tmp/mcp-audit]   # where wrangler writes index.js + bundle-meta.json
 *     [--top 40]                  # rows to print in the top-N section
 *     [--no-build]                # reuse an existing outdir's bundle-meta.json
 *
 * Bundle size doesn't change with dynamic imports — esbuild bundles them
 * inline (no code-splitting for Workers). What this script measures is the
 * shape of `index.js` itself, which is what V8 has to parse + load into every
 * fresh DO isolate at cold start. Use `profile-ram.ts` for heap-at-runtime;
 * use this script for "what's actually shipping".
 */
import { spawnSync } from 'child_process'
import { existsSync, readFileSync } from 'fs'
import { resolve } from 'path'

interface MetaInputRef {
    path: string
    kind?: string
}

interface MetaOutput {
    bytes: number
    inputs: Record<string, { bytesInOutput: number }>
}

interface MetaInput {
    bytes: number
    imports?: MetaInputRef[]
}

interface BundleMeta {
    inputs: Record<string, MetaInput>
    outputs: Record<string, MetaOutput>
}

const args = process.argv.slice(2)
const getFlag = (name: string, def: string): string => {
    const i = args.indexOf(name)
    const v = i >= 0 ? args[i + 1] : undefined
    return v ?? def
}
const hasFlag = (name: string): boolean => args.includes(name)

const OUTDIR = resolve(getFlag('--outdir', '/tmp/mcp-audit'))
const TOP_N = Number(getFlag('--top', '40'))
const SKIP_BUILD = hasFlag('--no-build')

function fmtKib(bytes: number): string {
    return (bytes / 1024).toFixed(1).padStart(8) + ' KiB'
}

function runWrangler(): void {
    console.info(`[audit-bundle] wrangler deploy --dry-run --outdir ${OUTDIR} --metafile`)
    const res = spawnSync('pnpm', ['wrangler', 'deploy', '--dry-run', '--outdir', OUTDIR, '--metafile'], {
        stdio: ['ignore', 'inherit', 'inherit'],
    })
    if (res.status !== 0) {
        throw new Error(`wrangler failed with exit code ${res.status}`)
    }
}

function loadMeta(): BundleMeta {
    const metafilePath = resolve(OUTDIR, 'bundle-meta.json')
    if (!existsSync(metafilePath)) {
        throw new Error(
            `bundle-meta.json not found at ${metafilePath} — run without --no-build or pass a populated --outdir`
        )
    }
    return JSON.parse(readFileSync(metafilePath, 'utf-8')) as BundleMeta
}

function findOutputIndex(meta: BundleMeta): string {
    const main = Object.keys(meta.outputs).find((k) => k.endsWith('index.js'))
    if (!main) {
        throw new Error(`no 'index.js' output found in metafile — outputs: ${Object.keys(meta.outputs).join(', ')}`)
    }
    return main
}

// Each input path gets bucketed by a coarse origin so the per-group summary
// answers "where is bundle weight coming from?" at a glance. Application code,
// auto-generated code, schema fixtures, and individual npm deps each get their
// own bucket. Unmatched paths fall through to a generic 'other' so we never
// hide weight by accident.
function classify(p: string): string {
    if (p.startsWith('src/generated/')) {
        return 'gen:src/generated (OpenAPI clients)'
    }
    if (p.startsWith('src/tools/generated/')) {
        return 'gen:src/tools/generated'
    }
    if (p.startsWith('src/tools/')) {
        return 'app:src/tools'
    }
    if (p.startsWith('src/schema/') || p.startsWith('schema/')) {
        return 'app:schema (JSON+TS)'
    }
    if (p.startsWith('src/lib/')) {
        return 'app:src/lib'
    }
    if (p.startsWith('src/')) {
        return 'app:src/* (other)'
    }
    const m = p.match(/node_modules\/\.pnpm\/([^@]+|@[^+]+\+[^@]+)@/)
    if (m && m[1]) {
        return 'dep:' + m[1].replace('+', '/')
    }
    if (p.includes('node_modules')) {
        return 'dep:other'
    }
    return 'other:' + p
}

function printTopModules(inputs: Record<string, { bytesInOutput: number }>, topN: number): void {
    const rows = Object.entries(inputs)
        .map(([path, v]) => ({ path, bytes: v.bytesInOutput }))
        .sort((a, b) => b.bytes - a.bytes)

    console.info(`\nTop ${topN} individual modules by bytesInOutput:`)
    for (const r of rows.slice(0, topN)) {
        console.info(`  ${fmtKib(r.bytes)}  ${r.path}`)
    }
}

function printGroups(inputs: Record<string, { bytesInOutput: number }>, total: number): void {
    const groups = new Map<string, number>()
    for (const [path, v] of Object.entries(inputs)) {
        const g = classify(path)
        groups.set(g, (groups.get(g) ?? 0) + v.bytesInOutput)
    }
    const rows = [...groups.entries()].sort((a, b) => b[1] - a[1])
    console.info(`\nPer-group bytesInOutput (top 30):`)
    for (const [g, b] of rows.slice(0, 30)) {
        const pct = ((b / total) * 100).toFixed(1).padStart(5)
        console.info(`  ${fmtKib(b)}  ${pct}%  ${g}`)
    }
}

function printGeneratedBreakdown(inputs: Record<string, { bytesInOutput: number }>): void {
    const folders = new Map<string, number>()
    for (const [path, v] of Object.entries(inputs)) {
        if (!path.startsWith('src/generated/')) {
            continue
        }
        const parts = path.split('/')
        const folder = parts.slice(0, 3).join('/')
        folders.set(folder, (folders.get(folder) ?? 0) + v.bytesInOutput)
    }
    const rows = [...folders.entries()].sort((a, b) => b[1] - a[1])
    if (rows.length === 0) {
        return
    }
    console.info(`\nsrc/generated/* per-API folder:`)
    for (const [folder, bytes] of rows) {
        console.info(`  ${fmtKib(bytes)}  ${folder}`)
    }
}

// Trace which inputs import a given target path. Useful for tracking down
// surprise transitive deps: we want to know who pulled in mime-db, not just
// that mime-db is in the bundle.
function findImporters(inputs: Record<string, MetaInput>, predicate: (importPath: string) => boolean): string[] {
    const importers = new Set<string>()
    for (const [path, v] of Object.entries(inputs)) {
        if (!v.imports) {
            continue
        }
        for (const imp of v.imports) {
            if (predicate(imp.path)) {
                importers.add(path)
                break
            }
        }
    }
    return [...importers]
}

interface TraceTarget {
    label: string
    predicate: (path: string) => boolean
    note?: string
}

const TRACE_TARGETS: TraceTarget[] = [
    {
        label: 'mime-db (compressed MIME database)',
        predicate: (p) => p.includes('/mime-db@') && p.endsWith('mime-db/db.json'),
    },
    {
        label: 'mime-types (consumer of mime-db)',
        predicate: (p) => p.includes('/mime-types@') && p.endsWith('mime-types/index.js'),
    },
    {
        label: 'yaml (~117 KiB)',
        predicate: (p) => /\/yaml@[^/]+\/node_modules\/yaml\/(browser|dist)\//.test(p),
    },
    {
        label: 'posthog-node (any version)',
        predicate: (p) => /\/posthog-node@[^/]+\/node_modules\/posthog-node\//.test(p),
    },
    {
        label: '@posthog/mcp (mcp-analytics wrapper package)',
        predicate: (p) => p.includes('/@posthog+mcp@') && p.endsWith('/index.mjs'),
    },
    {
        label: 'mimetext (transitive bring-in for mime-db via agents framework)',
        predicate: (p) => /\/mimetext@[^/]+\/node_modules\/mimetext\//.test(p),
    },
    {
        label: 'fflate (zip decompression for context-mill)',
        predicate: (p) => /\/fflate@[^/]+\/node_modules\/fflate\//.test(p),
    },
    {
        label: 'zod v3 layout',
        predicate: (p) => p.includes('/zod@') && p.includes('/zod/v3/'),
        note: 'zod@4.x ships both v3 and v4 layouts; both showing here means both APIs are reached',
    },
    {
        label: 'zod v4 layout',
        predicate: (p) => p.includes('/zod@') && p.includes('/zod/v4/'),
    },
]

function printTraces(inputs: Record<string, MetaInput>): void {
    console.info(`\nDependency traces (who imports each target):`)
    for (const target of TRACE_TARGETS) {
        const importers = findImporters(inputs, target.predicate).sort()
        console.info(`\n  ▸ ${target.label}  (${importers.length} importer${importers.length === 1 ? '' : 's'})`)
        if (target.note) {
            console.info(`    note: ${target.note}`)
        }
        if (importers.length === 0) {
            console.info(`    ✓ not present in bundle`)
            continue
        }
        // Highlight our own src/* importers — they're the directly actionable
        // ones. Dep-to-dep chains are informational; src-to-dep is "we did this".
        const ours = importers.filter((p) => p.startsWith('src/'))
        const deps = importers.filter((p) => !p.startsWith('src/'))
        for (const p of ours) {
            console.info(`    ★ ${p}  (our code)`)
        }
        for (const p of deps.slice(0, 8)) {
            console.info(`      ${p}`)
        }
        if (deps.length > 8) {
            console.info(`      … and ${deps.length - 8} more transitive importer(s)`)
        }
    }
}

function main(): void {
    if (!SKIP_BUILD) {
        runWrangler()
    } else {
        console.info(`[audit-bundle] --no-build set, reading existing bundle-meta.json from ${OUTDIR}`)
    }

    const meta = loadMeta()
    const main = findOutputIndex(meta)
    const output = meta.outputs[main]
    if (!output) {
        throw new Error(`output ${main} missing from metafile`)
    }
    const inputs = output.inputs
    const totalBytes = Object.values(inputs).reduce((s, v) => s + v.bytesInOutput, 0)

    console.info(`\n=== Bundle audit: ${main} ===`)
    console.info(`  output bytes (metafile):   ${output.bytes.toLocaleString()} bytes (${fmtKib(output.bytes).trim()})`)
    console.info(`  sum of bytesInOutput:      ${totalBytes.toLocaleString()} bytes (${fmtKib(totalBytes).trim()})`)
    console.info(`  input modules:             ${Object.keys(inputs).length.toLocaleString()}`)

    printTopModules(inputs, TOP_N)
    printGroups(inputs, totalBytes)
    printGeneratedBreakdown(inputs)
    printTraces(meta.inputs)
}

main()
