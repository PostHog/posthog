import * as fs from 'node:fs/promises'
import * as path from 'node:path'

export function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}

export function assertSafeDestination(root: string, destination: string, hint = ''): void {
    const normalizedRoot = path.resolve(root)
    const normalizedDestination = path.resolve(destination)
    if (normalizedDestination !== normalizedRoot && !normalizedDestination.startsWith(normalizedRoot + path.sep)) {
        throw new Error(`Refusing to write outside ${normalizedRoot}: ${normalizedDestination}${hint}`)
    }
}

/** Throws unless `target` stays inside `root` once symlinks are resolved, so a
 *  link committed into a checkout cannot redirect a write elsewhere. */
export async function assertResolvesInside(root: string, target: string, hint = ''): Promise<void> {
    const realRoot = await fs.realpath(root)
    const missing: string[] = []
    let existing = path.resolve(target)
    let realExisting: string
    for (;;) {
        try {
            realExisting = await fs.realpath(existing)
            break
        } catch (error) {
            if (errorCode(error) !== 'ENOENT') {
                throw error
            }
        }
        // A dangling link fails realpath too, but writing through it would create its target.
        const isLink = await fs.lstat(existing).then(
            (stats) => stats.isSymbolicLink(),
            () => false
        )
        if (isLink) {
            throw new Error(`Refusing to write through the dangling symlink ${existing}${hint}`)
        }
        missing.unshift(path.basename(existing))
        existing = path.dirname(existing)
    }
    assertSafeDestination(realRoot, path.join(realExisting, ...missing), hint)
}
