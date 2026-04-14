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
import { readFile } from 'node:fs/promises'
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

// --- run subcommands (shard-based flow) ---

const run = program.command('run').description('Shard-based run management')

run.command('create')
    .description('Create a new run (call once before shards)')
    .requiredOption('--type <type>', 'Run type (e.g., storybook, playwright)')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .option('--api <url>', 'API URL (overrides snapshots.yml config)')
    .option('--team <id>', 'Team ID (overrides snapshots.yml config)')
    .option('--repo <id>', 'Repo ID (UUID, overrides snapshots.yml config)')
    .option('--branch <name>', 'Git branch name')
    .option('--commit <sha>', 'Git commit SHA')
    .option('--pr <number>', 'PR number')
    .option('--token <value>', 'Personal API token')
    .option('--cookie <value>', 'Session cookie')
    .option('--purpose <purpose>', 'Run purpose: review or observe', 'review')
    .action(async (options: RunCreateOptions) => {
        try {
            const runId = await runCreate(options)
            // Output just the run ID so CI can capture it
            process.stdout.write(runId + '\n')
        } catch (error) {
            console.error('Error:', error)
            process.exit(1)
        }
    })

run.command('upload')
    .description('Hash and upload snapshots from a shard')
    .requiredOption('--run-id <id>', 'Run ID from `run create`')
    .requiredOption('--dir <path>', 'Directory containing PNG screenshots')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .option('--api <url>', 'API URL (overrides snapshots.yml config)')
    .option('--team <id>', 'Team ID (overrides snapshots.yml config)')
    .option('--token <value>', 'Personal API token')
    .option('--cookie <value>', 'Session cookie')
    .action(async (options: RunUploadOptions) => {
        try {
            await runUpload(options)
        } catch (error) {
            console.error('Error:', error)
            process.exit(1)
        }
    })

run.command('complete')
    .description('Complete a run after all shards have uploaded')
    .requiredOption('--run-id <id>', 'Run ID from `run create`')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .option('--api <url>', 'API URL (overrides snapshots.yml config)')
    .option('--team <id>', 'Team ID (overrides snapshots.yml config)')
    .option('--token <value>', 'Personal API token')
    .option('--cookie <value>', 'Session cookie')
    .option('--auto-approve', 'Auto-approve all changes and write signed baseline')
    .action(async (options: RunCompleteOptions) => {
        try {
            const exitCode = await runComplete(options)
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

interface RunCreateOptions {
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
    purpose?: string
}

interface RunUploadOptions {
    runId: string
    dir: string
    baseline: string
    api?: string
    team?: string
    token?: string
    cookie?: string
}

interface RunCompleteOptions {
    runId: string
    baseline: string
    api?: string
    team?: string
    token?: string
    cookie?: string
    autoApprove?: boolean
}

// --- Helpers ---

// Log to stderr so stdout stays clean for machine-readable output (e.g. run IDs)
function log(message: string): void {
    process.stderr.write(message + '\n')
}

function extractContentHash(signedHash: string): string {
    const parts = signedHash.split('.')
    return parts.length === 4 ? parts[2] : signedHash
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

function resolveConfig(options: { baseline: string; api?: string; team?: string; repo?: string }): {
    api: string
    team: string
    repo: string
} {
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

function makeClient(options: { baseline: string; api?: string; team?: string; token?: string; cookie?: string }): {
    client: VisualReviewClient
    api: string
    team: string
    repo: string
} {
    const config = resolveConfig(options)
    const client = new VisualReviewClient({
        apiUrl: config.api,
        teamId: config.team,
        token: options.token,
        sessionCookie: options.cookie,
    })
    return { client, ...config }
}

// --- Command implementations ---

// --- Shard command implementations ---

async function runCreate(options: RunCreateOptions): Promise<string> {
    const { client, repo } = makeClient(options)

    const branch = options.branch ?? getCurrentBranch()
    const commit = options.commit ?? getCurrentCommit()

    log(
        `Creating run: type=${options.type}, branch=${branch}, commit=${commit.slice(0, 10)}, purpose=${options.purpose ?? 'review'}`
    )

    const result = await client.createRun({
        repoId: repo,
        runType: options.type,
        commitSha: commit,
        branch,
        prNumber: options.pr ? parseInt(options.pr, 10) : undefined,
        snapshots: [],
        purpose: options.purpose,
    })

    log(`Run created: ${result.run_id}`)
    return result.run_id
}

async function runUpload(options: RunUploadOptions): Promise<void> {
    const { client } = makeClient(options)

    const dirPath = resolve(options.dir)

    // Scan and hash
    log(`Scanning ${dirPath} for PNGs...`)
    const scanned = scanDirectory(dirPath)
    if (scanned.length === 0) {
        log('No PNGs found — nothing to upload')
        return
    }

    const snapshots: Array<{ identifier: string; hash: string; width: number; height: number; data: Buffer }> = []
    log(`Found ${scanned.length} snapshots, hashing...`)
    const HASH_CONCURRENCY = 16
    for (let i = 0; i < scanned.length; i += HASH_CONCURRENCY) {
        const batch = scanned.slice(i, i + HASH_CONCURRENCY)
        const results = await Promise.all(
            batch.map(async ({ identifier, filePath }) => {
                const data = await readFile(filePath)
                const { hash, width, height } = await hashImageWithDimensions(data)
                return { identifier, hash, width, height, data }
            })
        )
        snapshots.push(...results)
    }

    log(`Sending ${snapshots.length} snapshots to backend`)

    // Send ALL identifiers — backend fetches baseline and classifies
    const addResult = await client.addSnapshots(options.runId, {
        snapshots: snapshots.map((s) => ({
            identifier: s.identifier,
            content_hash: s.hash,
            width: s.width,
            height: s.height,
        })),
    })

    log(`Registered ${addResult.added} snapshot(s), ${addResult.uploads.length} upload(s) needed`)

    // Upload artifacts
    if (addResult.uploads.length > 0) {
        const hashToSnapshot = new Map(snapshots.map((s) => [s.hash, s]))
        const CONCURRENCY = 10
        let uploaded = 0
        let failed = 0

        for (let i = 0; i < addResult.uploads.length; i += CONCURRENCY) {
            const batch = addResult.uploads.slice(i, i + CONCURRENCY)
            await Promise.all(
                batch.map(async (upload) => {
                    const snapshot = hashToSnapshot.get(upload.content_hash)
                    if (!snapshot) {
                        return
                    }
                    try {
                        await client.uploadToS3(upload, snapshot.data)
                        uploaded++
                    } catch (error) {
                        failed++
                        console.error(`  upload failed ${snapshot.identifier}: ${error}`)
                    }
                })
            )
        }
        log(`Uploaded ${uploaded} artifact(s)${failed > 0 ? `, ${failed} failed` : ''}`)
        if (failed > 0) {
            throw new Error(`${failed} artifact upload(s) failed`)
        }
    }
}

async function runComplete(options: RunCompleteOptions): Promise<number> {
    const { client } = makeClient(options)
    const baselinePath = resolve(options.baseline)

    log(`Completing run ${options.runId}`)

    // No body — shards already sent everything. Removal detection is a follow-up
    // (requires backend to track covered identifiers per shard).
    let run = await client.completeRun(options.runId)

    log(`Run status after complete: ${run.status}`)

    // Wait for diff processing
    if (run.status !== 'completed' && run.status !== 'failed') {
        log('Waiting for diff processing...')
        run = await waitForCompletion(client, options.runId)
    }

    const s = run.summary
    log(
        `\nRun complete: ${s.total} snapshots — ${s.unchanged} unchanged, ${s.changed} changed, ${s.new} new, ${s.removed} removed`
    )

    // Auto-approve if requested
    if (options.autoApprove) {
        log('Auto-approving all changes...')
        const approveResult = await client.autoApproveRun(options.runId)
        writeFileSync(baselinePath, approveResult.baseline_content, 'utf-8')
        log(`Baseline written to ${baselinePath} (${approveResult.baseline_content.length} bytes)`)
        return 0
    }

    // Exit code: 1 if changes detected, 0 if clean
    const hasChanges = s.changed > 0 || s.new > 0 || s.removed > 0
    if (hasChanges) {
        log('Visual changes detected — review required')
        return 1
    }

    log('No visual changes')
    return 0
}

// --- Legacy command implementations ---

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
            if (hash !== extractContentHash(baselineSignedHash)) {
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
    const HASH_CONCURRENCY = 16
    for (let i = 0; i < scanned.length; i += HASH_CONCURRENCY) {
        const batch = scanned.slice(i, i + HASH_CONCURRENCY)
        const results = await Promise.all(
            batch.map(async ({ identifier, filePath }) => {
                const data = await readFile(filePath)
                const { hash, width, height } = await hashImageWithDimensions(data)
                return { identifier, hash, width, height, data }
            })
        )
        snapshots.push(...results)
    }

    // 3. Create run with full manifest — backend fetches baseline and classifies
    const branch = options.branch ?? getCurrentBranch()
    const commit = options.commit ?? getCurrentCommit()
    log(`Creating run: ${snapshots.length} snapshots, branch=${branch}, commit=${commit.slice(0, 10)}`)

    const result = await client.createRun({
        repoId: repo,
        runType: options.type,
        commitSha: commit,
        branch,
        prNumber: options.pr ? parseInt(options.pr, 10) : undefined,
        purpose: options.autoApprove ? 'review' : 'observe',
        snapshots: snapshots.map((s) => ({
            identifier: s.identifier,
            content_hash: s.hash,
            width: s.width,
            height: s.height,
        })),
    })

    log(`Run created: ${result.run_id}`)
    log(
        `Backend requested ${result.uploads.length} upload(s), ${snapshots.length - result.uploads.length} already exist`
    )

    // 6. Upload missing artifacts (10 concurrent uploads)
    if (result.uploads.length > 0) {
        const hashToSnapshot = new Map(snapshots.map((s) => [s.hash, s]))
        const CONCURRENCY = 10
        let uploaded = 0
        let failed = 0

        const uploadOne = async (upload: (typeof result.uploads)[number]): Promise<void> => {
            const snapshot = hashToSnapshot.get(upload.content_hash)
            if (!snapshot) {
                return
            }
            try {
                await client.uploadToS3(upload, snapshot.data)
                uploaded++
            } catch (error) {
                failed++
                console.error(`  upload failed ${snapshot.identifier}: ${error}`)
            }
        }

        // Process in batches of CONCURRENCY
        for (let i = 0; i < result.uploads.length; i += CONCURRENCY) {
            const batch = result.uploads.slice(i, i + CONCURRENCY)
            await Promise.all(batch.map(uploadOne))
        }
        log(`Uploaded ${uploaded} artifact(s)${failed > 0 ? `, ${failed} failed` : ''}`)
        if (failed > 0) {
            throw new Error(`${failed} artifact upload(s) failed`)
        }
    }

    // 6. Complete run
    let run = await client.completeRun(result.run_id)
    log(`Run status after complete: ${run.status}`)

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
        log(`Baseline written to ${baselinePath} (${approveResult.baseline_content.length} bytes)`)
        return 0
    }

    // Without --auto-approve, unapproved changes exit 1 (gating)
    const hasChanges = s.changed > 0 || s.new > 0 || s.removed > 0
    if (hasChanges) {
        log('Visual changes detected — review required')
        return 1
    }

    log('No visual changes')
    return 0
}
