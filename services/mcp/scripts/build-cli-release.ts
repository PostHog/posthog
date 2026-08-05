import { build } from 'esbuild'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { copyInstructions } from './copy-instructions'
import { cliEsbuildOptions } from './hono-esbuild-config'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const mcpRoot = resolve(scriptDir, '..')
const repoRoot = resolve(mcpRoot, '../..')
const releaseOutfile = resolve(repoRoot, 'cli/lib/posthog-api-cli.mjs')

process.chdir(mcpRoot)

async function main(): Promise<void> {
    await mkdir(dirname(releaseOutfile), { recursive: true })
    // Populate the gitignored `shared/` tree (playbooks + guidelines) so esbuild
    // can inline it via `@shared/*`. Mirrors build-hono.ts.
    copyInstructions()
    await build(
        cliEsbuildOptions({
            outfile: releaseOutfile,
            sourcemap: false,
        })
    )

    console.info(`Built PostHog API CLI release bundle -> ${releaseOutfile}`)
}

main().catch((err: unknown) => {
    console.error('Build failed:', err)
    process.exit(1)
})
