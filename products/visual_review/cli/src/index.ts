#!/usr/bin/env node
/**
 * Visual Review CLI
 *
 * Commands:
 *   submit - Scan directory, hash PNGs, submit run, upload artifacts
 *   verify - Compare local screenshots against baseline (no API calls)
 */
import { program } from 'commander'
import { execSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { VisualReviewClient, type Run } from './client.js'
import { hashImageWithDimensions } from './hasher.js'
import { scanDirectory } from './scanner.js'
import { readBaselineHashes, readSnapshotsFile } from './snapshots.js'

program.name('vr').description('Visual Review CLI for snapshot testing').version('0.0.1')

// --- submit command ---

program
    .command('submit')
    .description('Scan directory for PNGs, hash them, and submit a run')
    .requiredOption('--dir <path>', 'Directory containing PNG screenshots')
    .requiredOption('--type <type>', 'Run type (e.g., storybook, playwright)')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .option('--api <url>', 'API URL (overrides snapshots.yml config)')
    .option('--team <id>', 'Team ID (overrides snapshots.yml config)')
    .option('--repo <id>', 'Repo ID (UUID, overrides snapshots.yml config)')
    .option('--branch <name>', 'Git branch name')
    .option('--commit <sha>', 'Git commit SHA')
    .option('--pr <number>', 'PR number')
    .option('--token <value>', 'Personal API token (Authorization: Bearer)')
    .option('--cookie <value>', 'Session cookie for authentication')
    .option('--auto-approve', 'Auto-approve all changes and write signed baseline')
    .action(async (options: SubmitOptions) => {
        try {
            const exitCode = await runSubmit(options)
            process.exit(exitCode)
        } catch (error) {
            console.error('Error:', error)
            process.exit(1)
        }
    })

// --- verify command ---

program
    .command('verify')
    .description('Compare local screenshots against baseline (no API calls)')
    .requiredOption('--dir <path>', 'Directory containing PNG screenshots')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .action(async (options: VerifyOptions) => {
        try {
            const exitCode = await runVerify(options)
            process.exit(exitCode)
        } catch (error) {
            console.error('Error:', error)
            process.exit(1)
        }
    })

program.parse()

// --- Types ---

interface VerifyOptions {
    dir: string
    baseline: string
}

interface SubmitOptions {
    dir: string
    type: string
    baseline: string
    api?: string
    team?: string
    repo?: string
    branch?: string
    commit?: string
    pr?: string
    token?: string
    cookie?: string
    autoApprove?: boolean
}

// --- Helpers ---

// Wrapper around stdout.write — console.log gets stripped by lint-staged
function log(message: string): void {
    process.stdout.write(message + '\n')
}

function getCurrentBranch(): string {
    try {
        return execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf-8' }).trim()
    } catch {
        return 'unknown'
    }
}

function getCurrentCommit(): string {
    try {
        return execSync('git rev-parse HEAD', { encoding: 'utf-8' }).trim()
    } catch {
        return 'unknown'
    }
}

function resolveConfig(options: SubmitOptions): { api: string; team: string; repo: string } {
    const baselinePath = resolve(options.baseline)
    const snapshotsFile = readSnapshotsFile(baselinePath)
    const config = snapshotsFile?.config

    const api = options.api ?? config?.api
    if (!api) {
        throw new Error('API URL required: pass --api or set config.api in snapshots.yml')
    }

    const team = options.team ?? config?.team
    if (!team) {
        throw new Error('Team ID required: pass --team or set config.team in snapshots.yml')
    }

    const repo = options.repo ?? config?.repo
    if (!repo) {
        throw new Error('Repo ID required: pass --repo or set config.repo in snapshots.yml')
    }

    return { api, team, repo }
}

// --- Command implementations ---

async function runVerify(options: VerifyOptions): Promise<number> {
    const dirPath = resolve(options.dir)
    const baselinePath = resolve(options.baseline)

    const scanned = scanDirectory(dirPath)

    if (scanned.length === 0) {
        console.error('No PNGs found in directory')
        return 1
    }

    const baselineHashes = readBaselineHashes(baselinePath)
    if (Object.keys(baselineHashes).length === 0) {
        console.error('No baseline hashes found — run `vr submit` on a PR first')
        return 1
    }

    log(`Found ${scanned.length} snapshots, verifying against ${Object.keys(baselineHashes).length} baselines...`)

    const changed: string[] = []
    const added: string[] = []

    for (const { identifier, filePath } of scanned) {
        const data = readFileSync(filePath)
        const { hash } = await hashImageWithDimensions(data)
        const baselineSignedHash = baselineHashes[identifier]

        if (!baselineSignedHash) {
            added.push(identifier)
        } else {
            // Extract the plain content hash from the signed format: v1.<kid>.<hash>.<tag>
            const parts = baselineSignedHash.split('.')
            const baselineContentHash = parts.length === 4 ? parts[2] : baselineSignedHash
            if (hash !== baselineContentHash) {
                changed.push(identifier)
            }
        }
    }

    const currentIds = new Set(scanned.map((s) => s.identifier))
    const removed = Object.keys(baselineHashes).filter((id) => !currentIds.has(id))

    const unchanged = scanned.length - changed.length - added.length
    log(
        `\n${scanned.length} snapshots — ${unchanged} unchanged, ${changed.length} changed, ${added.length} new, ${removed.length} removed`
    )

    if (changed.length > 0) {
        log('\nChanged:')
        changed.forEach((id) => log(`  - ${id}`))
    }
    if (added.length > 0) {
        log('\nNew:')
        added.forEach((id) => log(`  - ${id}`))
    }
    if (removed.length > 0) {
        log('\nRemoved:')
        removed.forEach((id) => log(`  - ${id}`))
    }

    if (changed.length > 0 || added.length > 0 || removed.length > 0) {
        log('\nBaseline mismatch — submit a PR to update baselines')
        return 1
    }

    log('All snapshots match baseline')
    return 0
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForCompletion(client: VisualReviewClient, runId: string): Promise<Run> {
    const maxAttempts = 120
    const intervalMs = 5000

    for (let i = 0; i < maxAttempts; i++) {
        const run = await client.getRun(runId)
        if (run.status === 'completed' || run.status === 'failed') {
            return run
        }
        await sleep(intervalMs)
    }

    throw new Error(`Run did not complete within ${(maxAttempts * intervalMs) / 1000}s`)
}

async function runSubmit(options: SubmitOptions): Promise<number> {
    const { api, team, repo } = resolveConfig(options)

    const client = new VisualReviewClient({
        apiUrl: api,
        teamId: team,
        token: options.token,
        sessionCookie: options.cookie,
    })

    // 1. Scan directory for PNGs
    const dirPath = resolve(options.dir)

    log(`Scanning ${dirPath} for PNGs...`)
    const scanned = scanDirectory(dirPath)

    if (scanned.length === 0) {
        console.error('No PNGs found in directory')
        return 1
    }

    // 2. Hash each image (decode PNG → RGBA → SHA256)
    const snapshots: Array<{
        identifier: string
        hash: string
        width: number
        height: number
        data: Buffer
    }> = []

    log(`Found ${scanned.length} snapshots, hashing...`)
    for (const { identifier, filePath } of scanned) {
        const data = readFileSync(filePath)
        const { hash, width, height } = await hashImageWithDimensions(data)
        snapshots.push({ identifier, hash, width, height, data })
    }

    // 3. Read baseline hashes (signed format — sent as-is, backend verifies)
    const baselinePath = resolve(options.baseline)
    const baselineHashes = readBaselineHashes(baselinePath)

    // 4. Create run with manifest
    const branch = options.branch ?? getCurrentBranch()
    const commit = options.commit ?? getCurrentCommit()

    const result = await client.createRun({
        repoId: repo,
        runType: options.type,
        commitSha: commit,
        branch,
        prNumber: options.pr ? parseInt(options.pr, 10) : undefined,
        snapshots: snapshots.map((s) => ({
            identifier: s.identifier,
            content_hash: s.hash,
            width: s.width,
            height: s.height,
        })),
        baselineHashes,
    })

    log(`Run created: ${result.run_id}`)

    // 5. Upload missing artifacts
    if (result.uploads.length > 0) {
        log(`Uploading ${result.uploads.length} artifacts...`)
        const hashToSnapshot = new Map(snapshots.map((s) => [s.hash, s]))

        for (const upload of result.uploads) {
            const snapshot = hashToSnapshot.get(upload.content_hash)
            if (!snapshot) {
                continue
            }

            try {
                await client.uploadToS3(upload, snapshot.data)
            } catch (error) {
                console.error(`  ✗ Upload failed: ${error}`)
            }
        }
    }

    // 6. Complete run
    let run = await client.completeRun(result.run_id)

    // 7. Wait for diff processing if still running
    if (run.status !== 'completed' && run.status !== 'failed') {
        log('Waiting for diff processing...')
        run = await waitForCompletion(client, result.run_id)
    }

    // 8. Print summary
    const s = run.summary
    log(
        `\nRun complete: ${s.total} snapshots — ${s.unchanged} unchanged, ${s.changed} changed, ${s.new} new, ${s.removed} removed`
    )

    // 9. Auto-approve if requested
    if (options.autoApprove) {
        log('Auto-approving all changes...')
        const approveResult = await client.autoApproveRun(result.run_id)
        const baselinePath = resolve(options.baseline)
        writeFileSync(baselinePath, approveResult.baseline_content, 'utf-8')
        log(`Baseline written to ${baselinePath}`)
        return 0
    }

    // 10. Exit code
    const hasChanges = s.changed > 0 || s.new > 0 || s.removed > 0
    if (hasChanges) {
        log('Visual changes detected — review required')
        return 1
    }

    log('No visual changes')
    return 0
}
