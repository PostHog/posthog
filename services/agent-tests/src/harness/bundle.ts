import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
/**
 * Bundle a fixture agent project and upload it to the local MinIO so
 * `AssServerExecutor` can download it through its real `BundleStore`.
 *
 * The bundling itself runs in a *child Node process* (via
 * `scripts/build-fixture.mjs`) — agent-stack's bundler is ESM-only and
 * pulling its dep chain through jest's CJS transformer is fragile. Child
 * process is a sharp seam: the test wants a tarball, the script gives it
 * a tarball, neither side has to know about the other's module system.
 *
 * The upload uses the AWS SDK directly (CJS-friendly) and targets the
 * same MinIO config Django writes through, so we're round-tripping
 * through the same object-storage layer prod does.
 */
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { basename, resolve as resolvePath } from 'node:path'

import { bundleStoreConfigFromEnv } from '@posthog/agent-core'

import type { CleanupRegistry } from './fixtures'

const SCRIPT_PATH = resolvePath(__dirname, '../../scripts/build-fixture.mjs')

interface RawBundle {
    agentSlug: string
    agentName: string
    tarballPath: string
    contentHash: string
    sizeBytes: number
}

export interface BundledAgent {
    /** Slug of the agent inside the bundle (from `agent.ts`'s `slug`). */
    agentSlug: string
    /** S3 object key the bundle was uploaded to. Goes onto AgentApplicationRevision.bundle_s3_key. */
    bundleS3Key: string
    /** Content hash of the tarball. Goes onto AgentApplicationRevision.bundle_sha256. */
    bundleSha256: string
    /** Size in bytes — used in the revision row for traceability. */
    sizeBytes: number
}

/**
 * Build a tarball for every agent under `projectDir` (via a child node
 * process) and upload each to MinIO. Returns one `BundledAgent` per
 * agent. The harness's cleanup deletes the S3 objects on suite teardown.
 *
 * One-shot per suite: bundling compiles TS (~few seconds). Call once in
 * `beforeAll`, reuse across cases.
 */
export async function bundleAndUpload(cleanup: CleanupRegistry, projectDir: string): Promise<BundledAgent[]> {
    const bundles = await runBundlerChildProcess(projectDir)
    if (bundles.length === 0) {
        throw new Error(`bundleAndUpload: no agents found under ${projectDir}`)
    }

    const config = bundleStoreConfigFromEnv()
    const s3 = new S3Client({
        endpoint: config.endpoint,
        region: config.region,
        credentials: {
            accessKeyId: config.accessKeyId,
            secretAccessKey: config.secretAccessKey,
        },
        forcePathStyle: config.forcePathStyle ?? true,
    })

    const uploaded: BundledAgent[] = []
    for (const bundle of bundles) {
        // Distinct key per suite run so concurrent runs / leftover state
        // can't collide.
        const key = `agent-tests/${bundle.agentSlug}/${bundle.contentHash}-${basename(bundle.tarballPath)}`
        const body = readFileSync(bundle.tarballPath)
        await s3.send(
            new PutObjectCommand({
                Bucket: config.bucket,
                Key: key,
                Body: body,
                ContentType: 'application/gzip',
            })
        )
        cleanup.register({
            description: `delete bundle s3://${config.bucket}/${key}`,
            run: async () => {
                const { DeleteObjectCommand } = await import('@aws-sdk/client-s3')
                await s3.send(new DeleteObjectCommand({ Bucket: config.bucket, Key: key })).catch(() => {
                    /* best-effort */
                })
            },
        })
        uploaded.push({
            agentSlug: bundle.agentSlug,
            bundleS3Key: key,
            bundleSha256: bundle.contentHash,
            sizeBytes: bundle.sizeBytes,
        })
    }
    s3.destroy()
    return uploaded
}

async function runBundlerChildProcess(projectDir: string): Promise<RawBundle[]> {
    return new Promise((resolve, reject) => {
        const child = spawn('node', [SCRIPT_PATH, projectDir], {
            stdio: ['ignore', 'pipe', 'pipe'],
            // The script imports from agent-stack workspace packages; cwd
            // doesn't change what `import` resolves but pnpm node_modules
            // still need to be on the resolver — the default cwd already
            // is the agent-tests package root, which is fine.
        })
        let stdout = ''
        let stderr = ''
        child.stdout.on('data', (chunk: Buffer) => {
            stdout += chunk.toString('utf8')
        })
        child.stderr.on('data', (chunk: Buffer) => {
            stderr += chunk.toString('utf8')
        })
        child.on('error', reject)
        child.on('exit', (code) => {
            if (code !== 0) {
                reject(new Error(`build-fixture exited ${code}\nstderr:\n${stderr}\nstdout:\n${stdout}`))
                return
            }
            // Last non-empty line is the JSON payload.
            const line = stdout
                .split('\n')
                .map((l) => l.trim())
                .filter(Boolean)
                .pop()
            if (!line) {
                reject(new Error(`build-fixture produced no output\nstderr:\n${stderr}`))
                return
            }
            try {
                const parsed = JSON.parse(line) as { bundles: RawBundle[] }
                resolve(parsed.bundles)
            } catch (err) {
                reject(new Error(`build-fixture output not JSON: ${(err as Error).message}\n${line}`))
            }
        })
    })
}
