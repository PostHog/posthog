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

/** Resolves `target` the way the kernel will when writing to it: one component at a time, following
 *  each link before applying a later `..`. Components past the first missing one are kept as written. */
async function resolveForWrite(target: string, hint: string): Promise<string> {
    const absolute = path.resolve(target)
    const pending = absolute.split(path.sep).filter(Boolean)
    let current = path.parse(absolute).root
    let hops = 0
    while (pending.length > 0) {
        const component = pending.shift()!
        if (component === '.') {
            continue
        }
        if (component === '..') {
            current = path.dirname(current)
            continue
        }
        const candidate = path.join(current, component)
        const stats = await fs.lstat(candidate).catch((error: unknown) => {
            if (errorCode(error) === 'ENOENT') {
                return null
            }
            throw error
        })
        if (stats?.isSymbolicLink()) {
            hops += 1
            if (hops > MAX_SYMLINK_HOPS) {
                throw new Error(`Refusing to follow too many symlinks at ${candidate}${hint}`)
            }
            const linkTarget = await fs.readlink(candidate)
            if (path.isAbsolute(linkTarget)) {
                current = path.parse(linkTarget).root
            }
            pending.unshift(...linkTarget.split(/[\\/]/).filter(Boolean))
            continue
        }
        current = candidate
    }
    return current
}

/** Throws unless `target` stays inside `root` once symlinks are resolved, so a
 *  link committed into a checkout cannot redirect a write elsewhere. */
export async function assertResolvesInside(root: string, target: string, hint = ''): Promise<void> {
    assertSafeDestination(await fs.realpath(root), await resolveForWrite(target, hint), hint)
}
