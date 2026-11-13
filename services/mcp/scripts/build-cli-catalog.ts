#!/usr/bin/env tsx
import { build } from 'esbuild'
import { createHash } from 'node:crypto'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { pathToFileURL } from 'node:url'

import { copyInstructions } from './copy-instructions'
import { honoEsbuildOptions } from './hono-esbuild-config'

const MCP_ROOT = path.resolve(__dirname, '..')
const ENTRY = path.resolve(MCP_ROOT, 'src/cli/catalog/build.ts')
const CLI_CATALOG_OUTFILE = path.resolve(MCP_ROOT, 'dist/cli-catalog.json')

async function main(outfile: string): Promise<void> {
    // tsx cannot load the `.md` template imports, so bundle the builder the way the server build does.
    copyInstructions()
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cli-catalog-'))
    const bundle = path.join(tmpDir, 'build.mjs')
    try {
        await build({
            ...honoEsbuildOptions(),
            entryPoints: [ENTRY],
            outfile: bundle,
            sourcemap: false,
            absWorkingDir: MCP_ROOT,
            logLevel: 'error',
        })
        const { buildCliCatalog } = (await import(
            pathToFileURL(bundle).href
        )) as typeof import('../src/cli/catalog/build')

        const catalog = buildCliCatalog(null)
        if (catalog.tools.length === 0) {
            throw new Error('The catalog has no tools.')
        }
        const contentHash = createHash('sha256').update(JSON.stringify(catalog)).digest('hex').slice(0, 16)

        fs.mkdirSync(path.dirname(outfile), { recursive: true })
        fs.writeFileSync(outfile, JSON.stringify({ ...catalog, build: contentHash }))
        console.info(`Wrote ${catalog.tools.length} tools to ${outfile}`)
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true })
    }
}

main(path.resolve(process.argv[2] ?? CLI_CATALOG_OUTFILE)).catch((error: unknown) => {
    console.error('Building the CLI tool catalog failed:', error)
    process.exit(1)
})
