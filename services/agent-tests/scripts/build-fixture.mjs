#!/usr/bin/env node
import { bundleProject } from '@repo/ass-bundler/bundle'
/**
 * Bundle a fixture project. Runs as a standalone Node ESM script so the
 * jest test process never has to load the (ESM-only) ass-bundler/config
 * packages — those import chains are deep and dragging them through
 * jest's CJS transformer is a constant fight.
 *
 * Usage:
 *   node scripts/build-fixture.mjs <fixtureDir>
 *
 * Stdout (last line, JSON):
 *   { "bundles": [{ "agentSlug": "...", "tarballPath": "...", "contentHash": "...", "sizeBytes": N }, ...] }
 *
 * Tests read the JSON, upload each tarball to MinIO, and register the
 * tarball path for cleanup.
 */
import { loadProject } from '@repo/ass-config/load-project'

const fixtureDir = process.argv[2]
if (!fixtureDir) {
    process.stderr.write('build-fixture: usage: build-fixture.mjs <fixtureDir>\n')
    process.exit(2)
}

try {
    const project = await loadProject(fixtureDir)
    const bundles = await bundleProject(project)
    const out = bundles.map((b) => ({
        agentSlug: b.agentSlug,
        agentName: b.agentName,
        tarballPath: b.tarballPath,
        contentHash: b.contentHash,
        sizeBytes: b.sizeBytes,
    }))
    process.stdout.write(JSON.stringify({ bundles: out }) + '\n')
} catch (err) {
    process.stderr.write(`build-fixture failed: ${err instanceof Error ? (err.stack ?? err.message) : String(err)}\n`)
    process.exit(1)
}
