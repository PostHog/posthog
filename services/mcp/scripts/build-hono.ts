import { build } from 'esbuild'

import { copyInstructions } from './copy-instructions'
import { honoEsbuildOptions, honoOutfile } from './hono-esbuild-config'

// Populate `shared/guidelines.md` so esbuild can inline it via `@shared/*`.
copyInstructions()

build(honoEsbuildOptions())
    .then(() => {
        console.info(`Built MCP server → ${honoOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
