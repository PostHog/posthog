#!/usr/bin/env tsx
/**
 * Summarizes what a PR changes for agents: tools added or removed, top-level params,
 * scopes, annotations and input schema size. Reads the tool schema snapshots and the
 * tool definitions JSON from two checkouts.
 *
 * The base side comes from `git archive <base-ref>`, so no second checkout or build runs.
 * Prints markdown to stdout, and nothing when a comparison ran and found no change.
 * Exit codes: 0 = compared (stdout may be empty), 3 = comparison unavailable (a side lacks
 * the snapshots, or reading failed; reason on stderr, stdout empty), anything else = crash.
 * Callers must not read empty output as "no change" unless the exit code is 0.
 *
 * Usage:
 *   pnpm --filter=@posthog/mcp exec tsx scripts/agent-api-diff.ts [--base-ref HEAD^1] [--base-dir <dir>]
 */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { parseArgs } from 'node:util'

import { diffToolSurfaces, loadToolSurface, renderAgentApiDiff } from './lib/agent-api-diff'

const REPO_ROOT = path.resolve(__dirname, '../../..')
const TRACKED_PATHS = ['services/mcp/schema', 'services/mcp/tests/unit/__snapshots__/tool-schemas']

const EXIT_UNAVAILABLE = 3

function extractBaseRef(baseRef: string, target: string): string | null {
    const archive = spawnSync('git', ['archive', baseRef, '--', ...TRACKED_PATHS], {
        cwd: REPO_ROOT,
        maxBuffer: 256 * 1024 * 1024,
    })
    if (archive.status !== 0) {
        console.warn(`Could not read ${baseRef}: ${archive.stderr?.toString().trim()}`)
        return null
    }
    const untar = spawnSync('tar', ['-x', '-C', target], { input: archive.stdout })
    if (untar.status !== 0) {
        console.warn(`Could not unpack ${baseRef}: ${untar.stderr?.toString().trim()}`)
        return null
    }
    return target
}

function main(): void {
    const { values } = parseArgs({
        options: { 'base-ref': { type: 'string', default: 'HEAD^1' }, 'base-dir': { type: 'string' } },
    })
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-api-base-'))
    try {
        const baseDir = values['base-dir'] ?? extractBaseRef(values['base-ref'] as string, scratch)
        const base = baseDir ? loadToolSurface(baseDir) : null
        const head = loadToolSurface(REPO_ROOT)
        if (!base || !head) {
            console.warn('Tool schema snapshots or definitions are missing on one side, so there is no agent API diff.')
            process.exitCode = EXIT_UNAVAILABLE
            return
        }
        process.stdout.write(renderAgentApiDiff(diffToolSurfaces(base, head)))
    } catch (error) {
        console.warn(`Could not compare tool surfaces: ${error}`)
        process.exitCode = EXIT_UNAVAILABLE
    } finally {
        fs.rmSync(scratch, { recursive: true, force: true })
    }
}

main()
