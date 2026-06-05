/**
 * In-memory bundle store. Used by tests and local dev. Same contract as the
 * eventual S3 impl.
 */

import { createHash } from 'crypto'

import { BundleEntry, BundleStore } from './bundle'

export class MemoryBundleStore implements BundleStore {
    private readonly files = new Map<string, Map<string, Buffer>>() // rev -> path -> bytes
    private readonly frozen = new Set<string>()

    private bundle(revisionId: string): Map<string, Buffer> {
        let b = this.files.get(revisionId)
        if (!b) {
            b = new Map()
            this.files.set(revisionId, b)
        }
        return b
    }

    private assertWritable(revisionId: string): void {
        if (this.frozen.has(revisionId)) {
            throw new Error(`bundle ${revisionId} is frozen`)
        }
    }

    async isFrozen(revisionId: string): Promise<boolean> {
        return this.frozen.has(revisionId)
    }

    async list(revisionId: string, prefix?: string): Promise<BundleEntry[]> {
        const b = this.bundle(revisionId)
        const entries: BundleEntry[] = []
        for (const [path, bytes] of b.entries()) {
            if (prefix && !path.startsWith(prefix)) {
                continue
            }
            entries.push({
                path,
                size: bytes.length,
                sha256: createHash('sha256').update(bytes).digest('hex'),
            })
        }
        entries.sort((a, b) => a.path.localeCompare(b.path))
        return entries
    }

    async read(revisionId: string, path: string): Promise<Buffer> {
        const b = this.bundle(revisionId).get(path)
        if (!b) {
            throw new Error(`file not found: ${revisionId}:${path}`)
        }
        return b
    }

    async readText(revisionId: string, path: string): Promise<string> {
        return (await this.read(revisionId, path)).toString('utf-8')
    }

    async write(revisionId: string, path: string, content: Buffer | string): Promise<void> {
        this.assertWritable(revisionId)
        const buf = typeof content === 'string' ? Buffer.from(content, 'utf-8') : content
        this.bundle(revisionId).set(path, buf)
    }

    async delete(revisionId: string, path: string): Promise<void> {
        this.assertWritable(revisionId)
        this.bundle(revisionId).delete(path)
    }

    async exists(revisionId: string, path: string): Promise<boolean> {
        return this.bundle(revisionId).has(path)
    }

    async freeze(revisionId: string): Promise<string> {
        const entries = await this.list(revisionId)
        const hash = createHash('sha256')
        for (const e of entries) {
            hash.update(e.path).update('\0').update(e.sha256).update('\0')
        }
        this.frozen.add(revisionId)
        return hash.digest('hex')
    }

    async copy(srcRev: string, srcPath: string, dstRev: string, dstPath: string): Promise<void> {
        const bytes = await this.read(srcRev, srcPath)
        await this.write(dstRev, dstPath, bytes)
    }

    /** Test/debug — fork a frozen bundle into a new draft. */
    async fork(srcRev: string, dstRev: string): Promise<void> {
        const src = this.bundle(srcRev)
        for (const [path, bytes] of src.entries()) {
            this.bundle(dstRev).set(path, bytes)
        }
    }
}
