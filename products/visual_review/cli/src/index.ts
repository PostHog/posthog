#!/usr/bin/env node
/**
 * Visual Review CLI
 *
 * Commands:
 *   submit - Scan directory, hash PNGs, submit run, upload artifacts
 */
import { program } from 'commander'
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { VisualReviewClient } from './client.js'
import { hashImageWithDimensions } from './hasher.js'
import { scanDirectory } from './scanner.js'
import { readSnapshots } from './snapshots.js'

program.name('vr').description('Visual Review CLI for snapshot testing').version('0.0.1')

// --- submit command ---

program
    .command('submit')
    .description('Scan directory for PNGs, hash them, and submit a run')
    .requiredOption('--dir <path>', 'Directory containing PNG screenshots')
    .requiredOption('--type <type>', 'Run type (e.g., storybook, playwright)')
    .requiredOption('--baseline <path>', 'Path to snapshots.yml baseline file')
    .requiredOption('--api <url>', 'API URL (e.g., http://localhost:8000)')
    .requiredOption('--team <id>', 'Team ID')
    .requiredOption('--project <id>', 'Project ID (UUID)')
    .option('--branch <name>', 'Git branch name', getCurrentBranch())
    .option('--commit <sha>', 'Git commit SHA', getCurrentCommit())
    .option('--pr <number>', 'PR number')
    .option('--token <value>', 'Personal API token (Authorization: Bearer)')
    .option('--cookie <value>', 'Session cookie for authentication')
    .action(async (options: SubmitOptions) => {
        try {
            const exitCode = await runSubmit(options)
            process.exit(exitCode)
        } catch (error) {
            console.error('Error:', error)
            process.exit(1)
        }
    })

program.parse()

// --- Types ---

interface SubmitOptions {
    dir: string
    type: string
    baseline: string
    api: string
    team: string
    project: string
    branch: string
    commit: string
    pr?: string
    token?: string
    cookie?: string
}

// --- Command implementations ---

async function runSubmit(options: SubmitOptions): Promise<number> {
    const client = new VisualReviewClient({
        apiUrl: options.api,
        teamId: options.team,
        token: options.token,
        sessionCookie: options.cookie,
    })

    // 1. Scan directory for PNGs
    const dirPath = resolve(options.dir)

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

    for (const { identifier, filePath } of scanned) {
        const data = readFileSync(filePath)
        const { hash, width, height } = await hashImageWithDimensions(data)
        snapshots.push({ identifier, hash, width, height, data })
    }

    // 3. Read baseline hashes
    const baselinePath = resolve(options.baseline)
    const baselineHashes = readSnapshots(baselinePath)

    // 4. Create run with manifest
    const result = await client.createRun({
        repoId: options.project,
        runType: options.type,
        commitSha: options.commit,
        branch: options.branch,
        prNumber: options.pr ? parseInt(options.pr, 10) : undefined,
        snapshots: snapshots.map((s) => ({
            identifier: s.identifier,
            content_hash: s.hash,
            width: s.width,
            height: s.height,
        })),
        baselineHashes,
    })

    // 5. Upload missing artifacts
    if (result.uploads.length > 0) {
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
    const run = await client.completeRun(result.run_id)

    // 7. Print summary

    // 8. Exit code
    const hasChanges = run.summary.changed > 0 || run.summary.new > 0 || run.summary.removed > 0
    if (hasChanges) {
        return 1
    }

    return 0
}

// --- Helpers ---

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
