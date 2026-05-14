import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { x as tarExtract } from 'tar'

export interface ExtractedBundle {
    /** Absolute path to the extracted bundle root. */
    readonly dir: string
    /** Removes the extracted directory. Always call this (preferably in a finally). */
    readonly cleanup: () => Promise<void>
}

/**
 * Writes the tarball to a temp file and extracts it into a sibling directory.
 * Returns the directory path plus a cleanup hook that removes the whole temp tree.
 *
 * We stage through the filesystem rather than streaming from memory because the
 * tar package's `file:` mode is the most reliable path and the bundle is small.
 */
export async function extractBundleToTempDir(buffer: Buffer): Promise<ExtractedBundle> {
    const base = await mkdtemp(join(tmpdir(), 'agent-bundle-'))
    const tarPath = join(base, 'bundle.tar.gz')
    const dir = join(base, 'extracted')
    await mkdir(dir, { recursive: true })
    await writeFile(tarPath, buffer)
    await tarExtract({ file: tarPath, cwd: dir, gzip: true })
    return {
        dir,
        cleanup: async () => {
            await rm(base, { recursive: true, force: true })
        },
    }
}
