import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { copyInstructions } from '../copy-instructions'
import { honoEsbuildOptions } from '../hono-esbuild-config'

async function main(): Promise<void> {
    const outDir = process.env.SDK_SCRATCH ?? resolve(process.cwd(), 'dist')
    mkdirSync(outDir, { recursive: true })
    const entry = resolve(process.cwd(), process.argv[2] ?? 'scripts/sdk/generate.ts')
    const outfile = resolve(outDir, `${entry.split('/').pop()!.replace(/\.ts$/, '')}.mjs`)
    copyInstructions()
    await build({
        ...honoEsbuildOptions({ outfile, sourcemap: false }),
        entryPoints: [entry],
        external: ['typescript'],
    })
    const run = spawnSync('node', [outfile, ...process.argv.slice(3)], { stdio: 'inherit', env: process.env })
    process.exit(run.status ?? 1)
}

main().catch((err: unknown) => {
    console.error(err)
    process.exit(1)
})
