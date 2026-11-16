#!/usr/bin/env node
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
 * With `--docs-repo`, it also lists the lines in that PostHog/posthog.com checkout that name a
 * removed tool.
 *
 * Usage:
 *   node services/mcp/scripts/agent-api-diff.ts [--base-ref HEAD^1] [--base-dir <dir>] [--docs-repo <dir>]
 */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { parseArgs } from 'node:util'

import {
    diffToolSurfaces,
    findDocsMentions,
    loadToolSurface,
    renderAgentApiDiff,
    renderDocsMentions,
} from './lib/agent-api-diff.ts'

const REPO_ROOT = path.resolve(import.meta.dirname, '../../..')
const TRACKED_PATHS = ['services/mcp/schema', 'services/mcp/tests/unit/__snapshots__/tool-schemas']

const EXIT_UNAVAILABLE = 3

function extractBaseRef(baseRef: string, target: string): string | null {
    // A commit-root archive prefetches unrelated blobs in a partial clone, even with a path filter.
    for (const trackedPath of TRACKED_PATHS) {
        const archive = spawnSync('git', ['archive', `--prefix=${trackedPath}/`, `${baseRef}:${trackedPath}`], {
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
    }
    return target
}

function main(): void {
    const { values } = parseArgs({
        options: {
            'base-ref': { type: 'string', default: 'HEAD^1' },
            'base-dir': { type: 'string' },
            'docs-repo': { type: 'string' },
        },
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
        const diff = diffToolSurfaces(base, head)
        process.stdout.write(renderAgentApiDiff(diff))
        const docsRepo = values['docs-repo']
        if (docsRepo) {
            const docsSha = spawnSync('git', ['-C', docsRepo, 'rev-parse', 'HEAD'], { encoding: 'utf-8' }).stdout.trim()
            const mentions = findDocsMentions(diff.removed, docsRepo, 'contents/docs')
            process.stdout.write(renderDocsMentions(mentions, `https://github.com/PostHog/posthog.com/blob/${docsSha}`))
        }
    } catch (error) {
        console.warn(`Could not compare tool surfaces: ${error}`)
        process.exitCode = EXIT_UNAVAILABLE
    } finally {
        fs.rmSync(scratch, { recursive: true, force: true })
    }
}

main()
