import * as fs from 'node:fs/promises'
import * as path from 'node:path'

export function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}

// Matches Linux's MAXSYMLINKS, so a link cycle fails instead of looping.
const MAX_SYMLINK_HOPS = 40

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
    let hops = 0
    for (;;) {
        try {
            realExisting = await fs.realpath(existing)
            break
        } catch (error) {
            if (errorCode(error) !== 'ENOENT') {
                throw error
            }
        }
        // realpath fails on a dangling link too, but writing through it creates its target.
        const isLink = await fs.lstat(existing).then(
            (stats) => stats.isSymbolicLink(),
            () => false
        )
        if (isLink) {
            hops += 1
            if (hops > MAX_SYMLINK_HOPS) {
                throw new Error(`Refusing to follow too many symlinks at ${existing}${hint}`)
            }
            // Splice the raw target on without normalizing it, so the OS resolves any `..` after
            // the links it passes through, with its own separators.
            const linkTarget = await fs.readlink(existing)
            existing = path.isAbsolute(linkTarget) ? linkTarget : `${path.dirname(existing)}${path.sep}${linkTarget}`
            continue
        }
        missing.unshift(path.basename(existing))
        existing = path.dirname(existing)
    }
    assertSafeDestination(realRoot, path.join(realExisting, ...missing), hint)
}
