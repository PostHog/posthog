/**
 * Filesystem-backed BundleStore. Each revision is a directory under `root`,
 * each path inside the revision is a regular file. Used by tests + local dev;
 * production swaps in S3.
 *
 * Freezing writes a `.frozen` marker file alongside the directory; subsequent
 * writes throw. (Cheap and good enough for v1.)
 */

import { createHash } from 'crypto'
import { promises as fs, statSync } from 'fs'
import * as path from 'path'

import { BundleEntry, BundleStore } from './bundle'

export class FsBundleStore implements BundleStore {
    constructor(private readonly root: string) {}

    private revDir(rev: string): string {
        return path.join(this.root, rev)
    }

    private filePath(rev: string, p: string): string {
        if (p.includes('..')) {
            throw new Error(`invalid path: ${p}`)
        }
        return path.join(this.revDir(rev), p)
    }

    private async isFrozen(rev: string): Promise<boolean> {
        try {
            await fs.access(path.join(this.revDir(rev), '.frozen'))
            return true
        } catch {
            return false
        }
    }

    async list(rev: string, prefix?: string): Promise<BundleEntry[]> {
        const dir = this.revDir(rev)
        try {
            await fs.access(dir)
        } catch {
            return []
        }
        const entries: BundleEntry[] = []
        await walk(dir, dir, entries)
        const filtered = prefix ? entries.filter((e) => e.path.startsWith(prefix)) : entries
        filtered.sort((a, b) => a.path.localeCompare(b.path))
        return filtered
    }

    async read(rev: string, p: string): Promise<Buffer> {
        return fs.readFile(this.filePath(rev, p))
    }

    async readText(rev: string, p: string): Promise<string> {
        return fs.readFile(this.filePath(rev, p), 'utf-8')
    }

    async write(rev: string, p: string, content: Buffer | string): Promise<void> {
        if (await this.isFrozen(rev)) {
            throw new Error(`bundle ${rev} is frozen`)
        }
        const full = this.filePath(rev, p)
        await fs.mkdir(path.dirname(full), { recursive: true })
        const buf = typeof content === 'string' ? Buffer.from(content, 'utf-8') : content
        await fs.writeFile(full, buf)
    }

    async delete(rev: string, p: string): Promise<void> {
        if (await this.isFrozen(rev)) {
            throw new Error(`bundle ${rev} is frozen`)
        }
        await fs.rm(this.filePath(rev, p), { force: true })
    }

    async exists(rev: string, p: string): Promise<boolean> {
        try {
            await fs.access(this.filePath(rev, p))
            return true
        } catch {
            return false
        }
    }

    async freeze(rev: string): Promise<string> {
        const entries = await this.list(rev)
        const hash = createHash('sha256')
        for (const e of entries.filter((x) => x.path !== '.frozen')) {
            hash.update(e.path).update('\0').update(e.sha256).update('\0')
        }
        const sha = hash.digest('hex')
        await fs.mkdir(this.revDir(rev), { recursive: true })
        await fs.writeFile(path.join(this.revDir(rev), '.frozen'), sha)
        return sha
    }

    async copy(srcRev: string, srcPath: string, dstRev: string, dstPath: string): Promise<void> {
        const bytes = await this.read(srcRev, srcPath)
        await this.write(dstRev, dstPath, bytes)
    }
}

async function walk(root: string, dir: string, out: BundleEntry[]): Promise<void> {
    const entries = await fs.readdir(dir, { withFileTypes: true })
    for (const entry of entries) {
        if (entry.name === '.frozen') {
            continue
        }
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            await walk(root, full, out)
            continue
        }
        const rel = path.relative(root, full).split(path.sep).join('/')
        const buf = await fs.readFile(full)
        const stat = statSync(full)
        out.push({
            path: rel,
            size: stat.size,
            sha256: createHash('sha256').update(buf).digest('hex'),
        })
    }
}
