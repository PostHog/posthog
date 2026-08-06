// Fails the build when the set of third-party packages inside the shipped bundle
// drifts from deps-allowlist.txt.
//
// A lockfile diff is easy to skim past; this makes every new transitive package a
// deliberate, reviewable line in a committed file. That matters more here than
// elsewhere: this service reads every platform integration credential we own, so
// "what code actually runs in this process" needs to be a short list somebody has
// read, not whatever npm resolved this week.
//
// Derived from the esbuild metafile rather than `pnpm list`, so it measures what is
// genuinely bundled into the artifact — a dependency that tree-shakes away entirely
// is not part of the running surface and does not need listing.
//
// To accept a change: `pnpm build && pnpm check:deps --write`, then review the diff.

import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { integrationServiceMetafile } from './integration-service-esbuild-config'

const ALLOWLIST_PATH = resolve(process.cwd(), 'deps-allowlist.txt')

interface Metafile {
    inputs: Record<string, unknown>
}

// `../../node_modules/.pnpm/hono@4.12.18/node_modules/hono/dist/index.js` -> `hono`
// `.../node_modules/@aws-sdk/client-kms/dist-es/index.js`                 -> `@aws-sdk/client-kms`
// The last node_modules/ segment wins, which is what makes the nested pnpm layout resolve correctly.
function packageNameFor(input: string): string | null {
    const marker = 'node_modules/'
    const at = input.lastIndexOf(marker)
    if (at === -1) {
        return null
    }
    const rest = input.slice(at + marker.length).split('/')
    const [first, second] = rest
    if (!first) {
        return null
    }
    return first.startsWith('@') && second ? `${first}/${second}` : first
}

function bundledPackages(metafile: Metafile): string[] {
    const names = new Set<string>()
    for (const input of Object.keys(metafile.inputs)) {
        const name = packageNameFor(input)
        if (name) {
            names.add(name)
        }
    }
    return [...names].sort()
}

async function main(): Promise<void> {
    let metafile: Metafile
    try {
        metafile = JSON.parse(await readFile(integrationServiceMetafile, 'utf8')) as Metafile
    } catch {
        console.error(`Could not read ${integrationServiceMetafile} — run \`pnpm build\` first.`)
        process.exit(1)
    }

    const actual = bundledPackages(metafile)

    if (process.argv.includes('--write')) {
        await writeFile(ALLOWLIST_PATH, `${actual.join('\n')}\n`)
        console.info(`Wrote ${actual.length} packages to deps-allowlist.txt — review the diff before committing.`)
        return
    }

    let allowed: string[]
    try {
        allowed = (await readFile(ALLOWLIST_PATH, 'utf8'))
            .split('\n')
            .map((l) => l.trim())
            .filter(Boolean)
    } catch {
        console.error('deps-allowlist.txt is missing — generate it with `pnpm build && pnpm check:deps --write`.')
        process.exit(1)
    }

    const allowedSet = new Set(allowed)
    const actualSet = new Set(actual)
    const added = actual.filter((name) => !allowedSet.has(name))
    const removed = allowed.filter((name) => !actualSet.has(name))

    if (added.length === 0 && removed.length === 0) {
        console.info(`Dependency allowlist OK — ${actual.length} packages bundled, all listed.`)
        return
    }

    if (added.length > 0) {
        console.error(`${added.length} package(s) are bundled but not in deps-allowlist.txt:\n`)
        for (const name of added) {
            console.error(`  + ${name}`)
        }
    }
    if (removed.length > 0) {
        console.error(`\n${removed.length} allowlisted package(s) are no longer bundled:\n`)
        for (const name of removed) {
            console.error(`  - ${name}`)
        }
    }
    console.error('\nIf this is intended, run `pnpm build && pnpm check:deps --write` and commit the result.')
    process.exit(1)
}

main().catch((err: unknown) => {
    console.error('check-deps-allowlist failed:', err)
    process.exit(1)
})
