// Fails the build if the bundle pulls in source from outside this package.
//
// This service holds the credentials for every third-party integration PostHog owns,
// so its dependency surface has to stay small enough that a human can audit it. The
// rule that keeps it small is simply "this package imports nothing from the rest of
// the monorepo" — no `nodejs/`, no `frontend/`, no shared `common/` packages. It
// shares the pnpm workspace only so dependency resolution works.
//
// Enforced against the esbuild metafile rather than the source, so a re-export chain
// cannot smuggle a module in: if it ended up in the shipped .mjs, it shows up here.
//
// Run after `pnpm build` (the build writes dist/meta.json).

import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { integrationServiceMetafile } from './integration-service-esbuild-config'

interface Metafile {
    inputs: Record<string, unknown>
}

async function main(): Promise<void> {
    let metafile: Metafile
    try {
        metafile = JSON.parse(await readFile(integrationServiceMetafile, 'utf8')) as Metafile
    } catch {
        console.error(`Could not read ${integrationServiceMetafile} — run \`pnpm build\` first.`)
        process.exit(1)
    }

    // esbuild resolves inputs relative to cwd (services/integration-service), so any
    // first-party file outside this package starts with '../'. Third-party code always
    // sits under a node_modules/ segment and is governed by check-deps-allowlist.ts.
    const foreign = Object.keys(metafile.inputs)
        .filter((input) => !input.includes('node_modules/'))
        .filter((input) => input.startsWith('..'))
        .sort()

    if (foreign.length > 0) {
        console.error('The integration-service bundle imports first-party code from outside its own package:\n')
        for (const input of foreign) {
            console.error(`  ${resolve(process.cwd(), input)}`)
        }
        console.error(
            '\nThis package must not depend on the rest of the monorepo — copy the small piece you need instead.'
        )
        process.exit(1)
    }

    console.info('Import boundary OK — no first-party imports from outside services/integration-service.')
}

main().catch((err: unknown) => {
    console.error('check-import-boundary failed:', err)
    process.exit(1)
})
